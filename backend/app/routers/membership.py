"""
Membership Router
Handles SBT minting and member management.

Thin HTTP layer: business logic lives in BlockchainService (see CLAUDE.md rule 5).
"""
from fastapi import APIRouter
import logging

from ..models import MintSBTRequest, MintSBTResponse
from ..services.blockchain_service import blockchain_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/membership", tags=["Membership"])


@router.post("/mint", response_model=MintSBTResponse)
async def mint_sbt(request: MintSBTRequest):
    """
    Register a DAO membership (demo of the future SBT mint).

    DEMO MODE: nothing is written on-chain yet (ROADMAP task 1.5, blocked on
    D-1/D-2), so tx_hash is null. Duplicate wallets are rejected.
    """
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
