"""
Blockchain Service
Handles Web3 operations, wallet connections, and SBT minting

DEMO MODE: no transaction is sent on-chain yet. Real minting is ROADMAP
task 1.5 and is blocked on architecture decisions D-1/D-2 (see docs/ROADMAP.md).
Until then this service only registers members in MongoDB and returns
tx_hash=None — it never fabricates a transaction hash.
"""
from typing import Optional, Tuple
import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from ..core.database import members_collection
from ..core.security_middleware import verify_eth_address
from ..models import Member

logger = logging.getLogger(__name__)


class BlockchainService:
    """Service for blockchain and Web3 operations"""

    @staticmethod
    async def mint_sbt(
        wallet_address: str,
        assurance_level: str,
        doc_hash: str
    ) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """
        Register a membership (off-chain demo of the future SBT mint)
        Returns: (success, token_id, tx_hash, error)

        tx_hash is always None until real on-chain minting lands (task 1.5).
        """
        if not verify_eth_address(wallet_address):
            return (False, None, None, "Dirección de wallet inválida")

        if not doc_hash:
            return (False, None, None, "Document hash requerido")

        try:
            address = wallet_address.lower()

            existing = await members_collection().find_one({"wallet_address": address})
            if existing:
                return (
                    False, None, None,
                    f"Ya existe un SBT para esta wallet (Token #{existing.get('token_id')})"
                )

            # Sequential id over the highest existing one: survives revocations
            # without colliding (count+1 does not). Replaced by the on-chain
            # tokenId when task 1.5 lands.
            last = await members_collection().find_one(sort=[("token_id", -1)])
            token_id = (last["token_id"] + 1) if last else 1

            member = Member(
                wallet_address=address,
                token_id=token_id,
                doc_hash=doc_hash,
                assurance_level=assurance_level
            )

            try:
                await members_collection().insert_one(member.model_dump())
            except DuplicateKeyError:
                # Unique index on wallet_address closed the race between the
                # duplicate check above and this insert.
                return (False, None, None, "Ya existe un SBT para esta wallet")

            logger.info(f"Membership registered (off-chain demo): Token #{token_id} for {address}")

            return (True, token_id, None, None)

        except Exception as e:
            logger.error(f"SBT minting error: {e}")
            return (False, None, None, str(e))
    
    @staticmethod
    async def get_member_by_wallet(wallet_address: str) -> Optional[Member]:
        """Get member by wallet address"""
        try:
            result = await members_collection().find_one({
                "wallet_address": wallet_address.lower()
            })
            if result:
                return Member(**result)
            return None
        except Exception as e:
            logger.error(f"Error getting member: {e}")
            return None
    
    @staticmethod
    async def get_member_by_token(token_id: int) -> Optional[Member]:
        """Get member by token ID"""
        try:
            result = await members_collection().find_one({"token_id": token_id})
            if result:
                return Member(**result)
            return None
        except Exception as e:
            logger.error(f"Error getting member by token: {e}")
            return None
    
    @staticmethod
    async def get_total_members() -> int:
        """Get total number of members"""
        try:
            return await members_collection().count_documents({})
        except Exception:
            return 0
    
    @staticmethod
    async def get_recent_members(days: int = 7) -> int:
        """Get number of members registered in the last N days"""
        try:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            return await members_collection().count_documents({
                "created_at": {"$gte": cutoff}
            })
        except Exception:
            return 0
    
    @staticmethod
    async def revoke_membership(token_id: int) -> Tuple[bool, Optional[str]]:
        """
        Revoke a membership (administrative action)
        Returns: (success, error)
        """
        try:
            result = await members_collection().update_one(
                {"token_id": token_id},
                {"$set": {"status": "revoked", "updated_at": datetime.now(timezone.utc)}}
            )
            
            if result.modified_count == 0:
                return (False, "Token no encontrado")
            
            logger.info(f"Membership revoked: Token #{token_id}")
            return (True, None)
            
        except Exception as e:
            logger.error(f"Revocation error: {e}")
            return (False, str(e))


# Singleton instance
blockchain_service = BlockchainService()
