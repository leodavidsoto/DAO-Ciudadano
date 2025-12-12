"""
Blockchain Service
Handles Web3 operations, wallet connections, and SBT minting
"""
from typing import Optional, Tuple
import logging
import uuid
from datetime import datetime, timezone

from ..core.database import members_collection
from ..core.config import settings
from ..models import Member

logger = logging.getLogger(__name__)


class BlockchainService:
    """Service for blockchain and Web3 operations"""
    
    # Contract configuration (testnet values)
    CONTRACT_ADDRESS = "0x" + "0" * 40  # Replace with actual contract
    CHAIN_ID = 11155111  # Sepolia testnet
    
    @staticmethod
    async def connect_wallet(address: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate and register wallet connection
        Returns: (success, validated_address, error)
        """
        if not address or len(address) != 42 or not address.startswith("0x"):
            return (False, None, "Dirección de wallet inválida")
        
        try:
            # Validate checksum address format
            addr_lower = address.lower()
            
            # Check if already registered
            existing = await members_collection().find_one({"wallet_address": addr_lower})
            if existing:
                logger.info(f"Wallet already registered: {addr_lower}")
            
            return (True, addr_lower, None)
            
        except Exception as e:
            logger.error(f"Wallet connection error: {e}")
            return (False, None, str(e))
    
    @staticmethod
    async def mint_sbt(
        wallet_address: str,
        assurance_level: str,
        doc_hash: str
    ) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """
        Mint a Soulbound Token for the citizen
        Returns: (success, token_id, tx_hash, error)
        """
        if not wallet_address or not wallet_address.startswith("0x"):
            return (False, None, None, "Wallet address inválida")
        
        if not doc_hash:
            return (False, None, None, "Document hash requerido")
        
        try:
            # Check if already minted
            existing = await members_collection().find_one({
                "wallet_address": wallet_address.lower()
            })
            
            if existing:
                return (
                    False, None, None, 
                    f"Ya existe un SBT para esta wallet (Token #{existing.get('token_id')})"
                )
            
            # Generate mock token (in production, this would call the smart contract)
            # TODO: Integrate with real Web3 contract interaction
            token_id = abs(hash(wallet_address + doc_hash)) % 1000000
            tx_hash = f"0x{uuid.uuid4().hex}{uuid.uuid4().hex[:24]}"
            
            # Store member
            member = Member(
                wallet_address=wallet_address.lower(),
                token_id=token_id,
                doc_hash=doc_hash,
                assurance_level=assurance_level
            )
            
            await members_collection().insert_one(member.model_dump())
            
            logger.info(f"SBT minted: Token #{token_id} for {wallet_address}")
            
            return (True, token_id, tx_hash, None)
            
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
