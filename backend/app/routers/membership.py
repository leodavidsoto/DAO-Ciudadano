"""
Membership Router
Handles SBT minting and member management
"""
from fastapi import APIRouter
from datetime import datetime, timezone
import logging
import asyncio

from ..models import MintSBTRequest, MintSBTResponse, Member
from ..core.security import generate_mock_tx_hash
from ..core.database import members_collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/membership", tags=["Membership"])


@router.post("/mint", response_model=MintSBTResponse)
async def mint_sbt(request: MintSBTRequest):
    """
    Mint a Soulbound Token (SBT) for verified citizen
    
    SBTs are non-transferable NFTs that represent DAO membership.
    In production, this would call a smart contract.
    """
    try:
        await asyncio.sleep(0.18)  # Simulate blockchain transaction time
        
        # Get next token ID
        existing_members = await members_collection().count_documents({})
        token_id = existing_members + 1
        
        # Generate mock transaction hash
        tx_hash = generate_mock_tx_hash()
        
        # Store member in database
        member = Member(
            wallet_address=request.wallet_address,
            token_id=token_id,
            doc_hash=request.doc_hash,
            assurance_level=request.assurance_level
        )
        await members_collection().insert_one(member.model_dump())
        
        logger.info(f"Minted SBT #{token_id} for {request.wallet_address}")
        
        return MintSBTResponse(
            ok=True,
            token_id=token_id,
            tx_hash=tx_hash
        )
        
    except Exception as e:
        logger.error(f"Error minting SBT: {e}")
        return MintSBTResponse(ok=False, error=str(e))


@router.get("/verify/{token_id}")
async def verify_membership(token_id: int):
    """
    Verify if a token ID represents valid DAO membership
    """
    member = await members_collection().find_one({"token_id": token_id})
    
    if member:
        return {
            "valid": True,
            "token_id": token_id,
            "wallet_address": member.get("wallet_address"),
            "assurance_level": member.get("assurance_level"),
            "status": member.get("status", "active"),
            "created_at": member.get("created_at")
        }
    
    return {"valid": False, "token_id": token_id}


@router.get("/member/{wallet_address}")
async def get_member_by_wallet(wallet_address: str):
    """
    Get member info by wallet address
    """
    member = await members_collection().find_one({"wallet_address": wallet_address})
    
    if member:
        member["_id"] = str(member["_id"])
        return {"found": True, "member": member}
    
    return {"found": False, "wallet_address": wallet_address}
