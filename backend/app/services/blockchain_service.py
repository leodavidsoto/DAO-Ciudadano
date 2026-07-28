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

from ..core.config import settings
from ..core.database import members_collection
from .chain_service import chain_service
from ..core.errors import report
from ..core.security_middleware import verify_eth_address
from ..models import Member

logger = logging.getLogger(__name__)

# Retries for the token_id allocation race (audit finding N-4).
MAX_TOKEN_ID_ATTEMPTS = 5


class BlockchainService:
    """Service for blockchain and Web3 operations"""

    @classmethod
    async def mint_sbt(
        cls,
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

            # === On-chain path (ROADMAP 1.5) ===
            # When the chain is configured, the contract is the source of
            # truth: it assigns the tokenId and enforces uniqueness. The Mongo
            # document becomes a cache of something that really happened,
            # instead of the only place the "membership" ever existed (C-2).
            if chain_service.enabled:
                return await cls._mint_on_chain(
                    address, assurance_level, doc_hash
                )

            # === Off-chain demo path ===
            # Reached only when the chain is NOT configured. It never claims a
            # transaction happened: tx_hash stays null.
            #
            # Sequential id over the highest existing one: survives revocations
            # without colliding (count+1 does not).
            #
            # Read-then-write is not atomic: two concurrent mints can compute
            # the same next id (audit finding N-4). The unique index on
            # token_id turns that into a DuplicateKeyError, which we retry.
            # Retrying is safe because the wallet uniqueness check already
            # passed and is itself protected by its own unique index.
            member = None
            for attempt in range(MAX_TOKEN_ID_ATTEMPTS):
                last = await members_collection().find_one(sort=[("token_id", -1)])
                token_id = (last["token_id"] + 1) if last else 1

                candidate = Member(
                    wallet_address=address,
                    token_id=token_id,
                    doc_hash=doc_hash,
                    assurance_level=assurance_level
                )

                try:
                    await members_collection().insert_one(candidate.model_dump())
                    member = candidate
                    break
                except DuplicateKeyError as e:
                    # Which unique index rejected it? wallet_address means the
                    # membership already exists (terminal); token_id means we
                    # lost the id race (retryable).
                    if "wallet_address" in str(e):
                        return (False, None, None, "Ya existe un SBT para esta wallet")
                    logger.info(
                        f"token_id {token_id} taken, retrying "
                        f"({attempt + 1}/{MAX_TOKEN_ID_ATTEMPTS})"
                    )

            if member is None:
                logger.error("Could not allocate a token_id after retries")
                return (False, None, None, "No se pudo asignar un ID de token; reintenta")

            token_id = member.token_id

            logger.info(f"Membership registered (off-chain demo): Token #{token_id} for {address}")

            return (True, token_id, None, None)

        except Exception as e:
            logger.error(f"SBT minting error: {e}")
            return (False, None, None, report(e, "mint_sbt"))
    
    @classmethod
    async def _mint_on_chain(cls, address, assurance_level, doc_hash):
        """Mint through the contract and record the result.

        The blocking web3 calls run in a worker thread: awaiting a receipt on
        the event loop would stall every other request for as long as the
        block takes.
        """
        import asyncio

        try:
            token_id, tx_hash = await asyncio.to_thread(
                chain_service.mint,
                address,
                doc_hash,
                assurance_level,
                settings.SBT_TOKEN_URI,
            )
        except Exception as e:
            # No silent fallback to a database write: reporting success for a
            # mint that did not happen is exactly the behaviour being removed.
            logger.error(f"On-chain mint failed for {address}: {e}", exc_info=True)
            return (False, None, None, report(e, "mint_on_chain",
                                              "No se pudo emitir la membresía en la blockchain"))

        if token_id is None:
            logger.error(f"Mint confirmed but no tokenId in the receipt: {tx_hash}")
            return (False, None, None,
                    "La transacción se confirmó pero no se pudo leer el ID del token")

        member = Member(
            wallet_address=address,
            token_id=token_id,
            doc_hash=doc_hash,
            assurance_level=assurance_level,
            tx_hash=tx_hash,
        )
        try:
            await members_collection().insert_one(member.model_dump())
        except DuplicateKeyError:
            # The token exists on-chain; only the local cache collided.
            logger.warning(f"Token #{token_id} minted on-chain but cache insert collided")

        logger.info(f"SBT minted on-chain: Token #{token_id} for {address} ({tx_hash})")
        return (True, token_id, tx_hash, None)

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
            return (False, report(e, "revoke_membership"))


# Singleton instance
blockchain_service = BlockchainService()
