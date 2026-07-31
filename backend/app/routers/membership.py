"""
Membership Router
Handles SBT minting and member management.

Thin HTTP layer: business logic lives in BlockchainService (see CLAUDE.md rule 5).

Wallet auth (cierra C-1): mintear una membresía requiere sesión de wallet
(SIWE) para la MISMA dirección que se registra — antes cualquiera podía
mintear "para" otra wallet con solo ponerla en el body.
"""
from fastapi import APIRouter, Depends
import logging

from ..models import MintSBTRequest, MintSBTResponse
from ..services.blockchain_service import blockchain_service
from .deps import current_address, ensure_acts_as_self

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/membership", tags=["Membership"])


@router.post("/mint", response_model=MintSBTResponse)
async def mint_sbt(request: MintSBTRequest, authenticated: str = Depends(current_address)):
    """
    Register a DAO membership (mints on-chain when configured, see
    chain_service.is_configured(); falls back to an off-chain demo record
    otherwise — tx_hash is null in that case). Duplicate wallets are rejected.
    """
    ensure_acts_as_self(request.wallet_address, authenticated, "mintear una membresía")
    ok, token_id, tx_hash, error = await blockchain_service.mint_sbt(
        wallet_address=request.wallet_address,
        assurance_level=request.assurance_level,
        doc_hash=request.doc_hash,
    )

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
        return {
            "valid": True,
            "token_id": token_id,
            "wallet_address": member.wallet_address,
            "assurance_level": member.assurance_level,
            "status": member.status,
            "created_at": member.created_at,
        }

    return {"valid": False, "token_id": token_id}


@router.get("/member/{wallet_address}")
async def get_member_by_wallet(wallet_address: str):
    """
    Get member info by wallet address
    """
    member = await blockchain_service.get_member_by_wallet(wallet_address)

    if member:
        return {"found": True, "member": member.model_dump()}

    return {"found": False, "wallet_address": wallet_address}
