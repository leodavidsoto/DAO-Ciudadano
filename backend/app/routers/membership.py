"""
Membership Router
Handles SBT minting and member management.

Thin HTTP layer: business logic lives in BlockchainService (see CLAUDE.md rule 5).

Wallet auth (cierra C-1): mintear una membresía requiere sesión de wallet
(SIWE) para la MISMA dirección que se registra — antes cualquiera podía
mintear "para" otra wallet con solo ponerla en el body.
"""
from fastapi import APIRouter, Depends, HTTPException
import logging

from ..models import MintSBTRequest, MintSBTResponse
from ..services.blockchain_service import MintingUnavailable, blockchain_service
from ..services.membership_verifier import membership_is_onchain, membership_is_valid
from .deps import current_address, ensure_acts_as_self

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
