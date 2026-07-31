"""
Blockchain Service
Handles Web3 operations, wallet connections, and SBT minting

Minteo real (ROADMAP tarea 1.5, D-1): si chain_service.is_configured() es
verdadero (SEPOLIA_RPC_URL + SBT_CONTRACT_ADDRESS + MINTER_PRIVATE_KEY),
esta función envía una transacción real a DAOCiudadanaSBT.mintMembership()
y guarda el tx_hash devuelto por la cadena. Si no está configurado, cae a
modo demo (solo MongoDB, tx_hash=None) — nunca fabrica un tx_hash falso.
"""
from typing import Optional, Tuple
import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from ..core.database import members_collection
from ..core.security_middleware import verify_eth_address
from ..core.identity import document_identity_hash_hex
from ..models import Member
from . import chain_service

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

            tx_hash: Optional[str] = None
            onchain_token_id: Optional[int] = None

            if chain_service.is_configured():
                try:
                    identity_hash_hex = document_identity_hash_hex(doc_hash)
                    tx_hash, onchain_token_id = chain_service.mint_sbt_onchain(
                        wallet_address=address,
                        identity_hash_hex=identity_hash_hex,
                        assurance_level=assurance_level,
                    )
                except chain_service.ChainMintError as e:
                    logger.error(f"On-chain mint failed for {address}: {e}")
                    return (False, None, None, f"Error al mintear on-chain: {e}")

            # Sequential id over the highest existing one: survives revocations
            # without colliding (count+1 does not). Overridden by the real
            # on-chain tokenId when minting actually happened on-chain.
            last = await members_collection().find_one(sort=[("token_id", -1)])
            token_id = onchain_token_id if onchain_token_id is not None else ((last["token_id"] + 1) if last else 1)

            member = Member(
                wallet_address=address,
                token_id=token_id,
                doc_hash=doc_hash,
                assurance_level=assurance_level
            )

            member_dict = member.model_dump()
            if tx_hash:
                member_dict["tx_hash"] = tx_hash

            try:
                await members_collection().insert_one(member_dict)
            except DuplicateKeyError:
                # Unique index on wallet_address closed the race between the
                # duplicate check above and this insert.
                return (False, None, None, "Ya existe un SBT para esta wallet")

            if tx_hash:
                logger.info(f"Membership minted on-chain: Token #{token_id} for {address} (tx {tx_hash})")
            else:
                logger.info(f"Membership registered (off-chain demo): Token #{token_id} for {address}")

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
