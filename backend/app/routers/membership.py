"""
Membership Router
Handles SBT minting and member management.

Thin HTTP layer: business logic lives in BlockchainService (see CLAUDE.md rule 5).

Wallet auth (cierra C-1): mintear una membresía requiere sesión de wallet
(SIWE) para la MISMA dirección que se registra — antes cualquiera podía
mintear "para" otra wallet con solo ponerla en el body.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import List
from datetime import datetime, timezone
import asyncio
import logging

from pymongo.errors import DuplicateKeyError

from ..core.database import get_collection
from ..models import MintSBTRequest, MintSBTResponse
from ..services import chain_service
from ..services.blockchain_service import MintingUnavailable, blockchain_service
from ..services.membership_verifier import membership_is_onchain, membership_is_valid
from .deps import current_address, ensure_acts_as_self


def mint_operations_collection():
    """Operaciones de minteo, para idempotencia y reconciliación."""
    return get_collection("mint_operations")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/membership", tags=["Membership"])


@router.post("/mint", response_model=MintSBTResponse)
async def mint_sbt(request: MintSBTRequest, authenticated: str = Depends(current_address)):
    """
    Register a DAO membership using the explicit MINT_MODE. On-chain mode
    never falls back to Mongo-only demo behavior. Production remains blocked
    until identity verification is bound to the authenticated wallet.
    """
    ensure_acts_as_self(request.wallet_address, authenticated, "mintear una membresía")
    try:
        ok, token_id, tx_hash, error = await blockchain_service.mint_sbt(
            wallet_address=request.wallet_address,
            assurance_level=request.assurance_level,
            doc_hash=request.doc_hash,
        )
    except MintingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not ok:
        return MintSBTResponse(ok=False, error=error)

    return MintSBTResponse(ok=True, token_id=token_id, tx_hash=tx_hash)


@router.get("/verify/{token_id}")
async def verify_membership(token_id: int):
    """
    Verify if a token ID represents valid DAO membership
    """
    member = await blockchain_service.get_member_by_token(token_id)

    if member:
        member_data = member.model_dump()
        return {
            "valid": membership_is_valid(member_data),
            "onchain": membership_is_onchain(member_data),
            "token_id": token_id,
            "wallet_address": member.wallet_address,
            "assurance_level": member.assurance_level,
            "status": member.status,
            "issuance_mode": member.issuance_mode,
            "identity_verified": member.identity_verified,
            "tx_hash": member.tx_hash,
            "created_at": member.created_at,
        }

    return {"valid": False, "onchain": False, "token_id": token_id}


@router.get("/member/{wallet_address}")
async def get_member_by_wallet(wallet_address: str):
    """
    Get member info by wallet address
    """
    member = await blockchain_service.get_member_by_wallet(wallet_address)

    if member:
        member_data = member.model_dump()
        # `doc_hash` is an internal identity-binding input, not public profile
        # data. Return only what the UI needs to resume an existing membership.
        return {
            "found": True,
            "member": {
                "wallet_address": member.wallet_address,
                "token_id": member.token_id,
                "assurance_level": member.assurance_level,
                "status": member.status,
                "valid": membership_is_valid(member_data),
                "onchain": membership_is_onchain(member_data),
                "issuance_mode": member.issuance_mode,
                "identity_verified": member.identity_verified,
                "tx_hash": member.tx_hash,
                "created_at": member.created_at,
            },
        }

    return {"found": False, "wallet_address": wallet_address}


# === Minteo con prueba ZK (ADR-001, D-1/D-2) ===================================

class ZkMintRequest(BaseModel):
    """Todo lo que el relayer necesita. Nada más.

    No hay `doc_hash`, ni nivel de aseguramiento, ni ruta Merkle, ni la firma
    del emisor: el ciudadano ya probó su elegibilidad localmente y esos datos
    no deben salir de su dispositivo.
    """

    wallet_address: str
    pA: List[str]
    pB: List[List[str]]
    pC: List[str]
    nullifier_hash: str
    identity_root: str

    @field_validator("pA", "pC")
    @classmethod
    def validate_g1(cls, v):
        if len(v) != 2:
            raise ValueError("Los componentes G1 de la prueba tienen dos coordenadas.")
        return v

    @field_validator("pB")
    @classmethod
    def validate_g2(cls, v):
        if len(v) != 2 or any(len(row) != 2 for row in v):
            raise ValueError("El componente G2 de la prueba es una matriz 2x2.")
        return v

    @field_validator("nullifier_hash")
    @classmethod
    def validate_nullifier(cls, v):
        raw = v.strip()
        if not raw.startswith("0x") or len(raw) != 66:
            raise ValueError("nullifier_hash debe ser bytes32 en hexadecimal (0x + 64).")
        int(raw, 16)  # lanza si no es hex
        return raw


@router.post("/mint-zk", response_model=MintSBTResponse)
async def mint_with_zk_proof(
    request: ZkMintRequest,
    authenticated: str = Depends(current_address),
):
    """Relayer: envía la prueba on-chain y patrocina el gas.

    Exige sesión SIWE para la MISMA wallet. Eso no protege del front-running
    —de eso se encarga el circuito, que liga `recipient` dentro de la hoja—
    pero impide que un tercero gaste el gas de la DAO enviando pruebas ajenas.
    """
    ensure_acts_as_self(request.wallet_address, authenticated, "mintear una membresía")

    # Idempotencia: un reintento tras un timeout no puede enviar otra
    # transacción. El nullifier es el identificador natural de la operación —
    # el contrato lo rechazaría, pero para entonces el gas ya se gastó.
    existing = await mint_operations_collection().find_one(
        {"nullifier_hash": request.nullifier_hash.lower()}
    )
    if existing and existing.get("status") == "confirmed":
        return MintSBTResponse(
            ok=True,
            token_id=existing.get("token_id"),
            tx_hash=existing.get("tx_hash"),
        )
    if existing and existing.get("status") == "pending":
        raise HTTPException(
            status_code=409,
            detail="Ya hay un minteo en curso para esta credencial. Espera a que confirme.",
        )

    try:
        await mint_operations_collection().insert_one({
            "nullifier_hash": request.nullifier_hash.lower(),
            "wallet_address": request.wallet_address.lower(),
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        })
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Ya hay un minteo en curso para esta credencial. Espera a que confirme.",
        )

    try:
        tx_hash, token_id = await asyncio.to_thread(
            chain_service.mint_with_proof,
            wallet_address=request.wallet_address,
            proof_a=request.pA,
            proof_b=request.pB,
            proof_c=request.pC,
            nullifier_hash=request.nullifier_hash,
            identity_root=int(request.identity_root),
        )
    except chain_service.ChainMintError as exc:
        # La operación queda marcada como fallida, no colgada en `pending`:
        # de lo contrario el ciudadano no podría reintentar nunca.
        await mint_operations_collection().update_one(
            {"nullifier_hash": request.nullifier_hash.lower()},
            {"$set": {"status": "failed", "error": type(exc).__name__}},
        )
        logger.error("ZK mint failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="No se pudo confirmar el minteo on-chain. Intenta más tarde.",
        ) from exc

    await mint_operations_collection().update_one(
        {"nullifier_hash": request.nullifier_hash.lower()},
        {"$set": {
            "status": "confirmed",
            "tx_hash": tx_hash,
            "token_id": token_id,
            "confirmed_at": datetime.now(timezone.utc),
        }},
    )

    return MintSBTResponse(ok=True, token_id=token_id, tx_hash=tx_hash)
