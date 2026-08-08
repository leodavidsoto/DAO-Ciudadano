"""
Membership Router
Handles SBT minting and member management.

Thin HTTP layer: business logic lives in BlockchainService (see CLAUDE.md rule 5).

Wallet auth (cierra C-1): mintear una membresía requiere sesión de wallet
(SIWE) para la MISMA dirección que se registra — antes cualquiera podía
mintear "para" otra wallet con solo ponerla en el body.

Verificación de identidad (cierra P-4, ROADMAP 1.10): además de la sesión,
`POST /mint` exige un `membership_grant` — el JWT que el servidor firmó al
terminar un flujo civil real. El nivel de aseguramiento y el índice del
documento salen de ese token, no del body: SIWE prueba control de una wallet,
nunca que la persona detrás completó verificación alguna.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from typing import List
import asyncio
import logging

from ..models import MintSBTRequest, MintSBTResponse
from ..services import chain_service, membership_grant, mint_operations
from ..services.blockchain_service import MintingUnavailable, blockchain_service
from ..services.membership_verifier import (
    invalidate_cached_membership,
    membership_is_onchain,
    membership_is_valid,
)
from .deps import current_address, ensure_acts_as_self

# El ciclo de vida de las operaciones vive en `services/` (regla 7 de
# AGENTS.md). Se reexporta porque es el punto de entrada que ya usan los tests
# y los scripts de operación.
mint_operations_collection = mint_operations.mint_operations_collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/membership", tags=["Membership"])


@router.post("/mint", response_model=MintSBTResponse)
async def mint_sbt(
    request: MintSBTRequest, authenticated: str = Depends(current_address)
):
    """Da de alta una membresía consumiendo un grant de identidad de un solo uso.

    Orden deliberado:

      1. La sesión SIWE debe ser de ESTA wallet (C-1).
      2. Se valida el grant —firma, vigencia, emisor, audiencia— ANTES de
         tocar la base: un token inválido no debe dejar rastro de intento.
      3. Se reclama el jti, que queda atado a esta wallet. Aquí es donde el
         token deja de servirle a nadie más.
      4. Solo entonces se registra la membresía, con el nivel y el índice de
         documento que certificó el servidor.

    Si el paso 4 falla, el grant se libera (`release`): la persona reintenta
    con el mismo token sin repetir el flujo civil. Solo el éxito lo consume
    definitivamente (`finalize`). Ver `services/membership_grant.py`.
    """
    ensure_acts_as_self(request.wallet_address, authenticated, "mintear una membresía")

    # Antes de tocar el grant: si este despliegue no puede dar altas, quemar el
    # jti para nada dejaría a la persona con una verificación gastada por un
    # problema de configuración del servidor.
    try:
        blockchain_service.ensure_minting_available()
    except MintingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        claims = membership_grant.verify(request.membership_grant)
    except membership_grant.MembershipGrantError as exc:
        # 403 y no 401: la sesión de wallet es válida; lo que falta es la
        # verificación de identidad.
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        await membership_grant.claim(claims, request.wallet_address)
    except membership_grant.MembershipGrantError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        ok, token_id, tx_hash, error = await blockchain_service.mint_sbt(
            wallet_address=request.wallet_address,
            assurance_level=claims.assurance_level,
            # El índice ciego del sujeto ES el vínculo con el documento. El
            # servidor nunca vio el documento, así que no hay nada mejor que
            # esto y —a diferencia del `doc_hash` anterior— no lo eligió el
            # cliente.
            doc_hash=claims.subject_key,
        )
    except MintingUnavailable as exc:
        # La configuración cambió entre la comprobación y el intento. La
        # verificación sigue viva: se libera para que reintente.
        await membership_grant.release(claims.jti, "minting_unavailable")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not ok:
        await membership_grant.release(claims.jti, error or "mint_failed")
        return MintSBTResponse(ok=False, error=error)

    # Estado terminal: hay membresía, el grant no vuelve a servir.
    await membership_grant.finalize(claims.jti, token_id)

    # La caché de hasMembership() pudo guardar un "no es miembro" hace
    # segundos; sin invalidarla, quien acaba de mintear vería 403 al votar
    # durante el resto del TTL.
    invalidate_cached_membership(request.wallet_address)

    return MintSBTResponse(
        ok=True,
        token_id=token_id,
        tx_hash=tx_hash,
        assurance_level=claims.assurance_level,
    )


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
            raise ValueError(
                "nullifier_hash debe ser bytes32 en hexadecimal (0x + 64)."
            )
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

    nullifier = request.nullifier_hash.lower()

    # Idempotencia y reconciliación viven en el servicio: una operación abierta
    # se resuelve contra la cadena antes de rechazar el reintento, así que una
    # caída del worker deja de convertir la credencial en un 409 sin salida.
    decision = await mint_operations.begin(nullifier, request.wallet_address)

    if decision.action == "confirmed":
        return MintSBTResponse(
            ok=True, token_id=decision.token_id, tx_hash=decision.tx_hash
        )
    if decision.action == "in_flight":
        raise HTTPException(status_code=409, detail=decision.detail)
    if decision.action == "needs_review":
        raise HTTPException(status_code=409, detail=decision.detail)

    # El hash se persiste desde el hilo del RPC en cuanto la transacción se
    # difunde, sin esperar el recibo: es lo único que permite reconciliar
    # después una transacción real cuyo proceso murió durante la espera.
    loop = asyncio.get_running_loop()
    submitted: dict[str, str] = {}

    def record_submission(tx_hash: str) -> None:
        submitted["tx_hash"] = tx_hash
        asyncio.run_coroutine_threadsafe(
            mint_operations.mark_submitted(nullifier, tx_hash), loop
        ).result(timeout=10)

    try:
        tx_hash, token_id = await asyncio.to_thread(
            chain_service.mint_with_proof,
            wallet_address=request.wallet_address,
            proof_a=request.pA,
            proof_b=request.pB,
            proof_c=request.pC,
            nullifier_hash=request.nullifier_hash,
            identity_root=int(request.identity_root),
            on_submitted=record_submission,
        )
    except chain_service.ChainMintError as exc:
        logger.error("ZK mint failed: %s", exc)
        if submitted:
            # La transacción salió. Marcarla `failed` aquí es lo que hacía que
            # el reintento enviase una segunda y quemara gas contra un revert
            # seguro por nullifier repetido. Queda `submitted` y la resuelve la
            # cadena, en el próximo intento o en el barrido.
            await mint_operations.mark_submitted(nullifier, submitted["tx_hash"])
            raise HTTPException(
                status_code=409,
                detail=(
                    f"La transacción de minteo se envió (tx {submitted['tx_hash']}) "
                    "pero aún no se pudo confirmar. Reintenta en unos minutos: si "
                    "ya confirmó, recibirás tu credencial sin volver a gastar gas."
                ),
            ) from exc
        # Nada se difundió: reintentable de inmediato.
        await mint_operations.mark_failed(nullifier, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="No se pudo confirmar el minteo on-chain. Intenta más tarde.",
        ) from exc

    # Confirmar cierra la operación y refleja el SBT en `members`: sin eso,
    # /membership/member/{wallet} y el gate de gobernanza no ven la credencial
    # recién emitida.
    await mint_operations.mark_confirmed(
        nullifier_hash=nullifier,
        wallet_address=request.wallet_address,
        tx_hash=tx_hash,
        token_id=token_id,
    )

    return MintSBTResponse(ok=True, token_id=token_id, tx_hash=tx_hash)
