"""
Blockchain Service
Handles Web3 operations, wallet connections, and SBT minting

`MINT_MODE` makes the behavior explicit: disabled, demo (Mongo only) or
onchain. There is no automatic fallback from onchain to demo. Production is
blocked until a one-time identity verification grant is bound to the wallet.
"""

from typing import Optional, Tuple
import asyncio
import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from ..core.config import settings
from ..core.database import members_collection
from ..core.security_middleware import verify_eth_address
from ..core.identity import document_identity_hash_hex
from ..models import Member
from . import chain_service

logger = logging.getLogger(__name__)


class MintingUnavailable(RuntimeError):
    """The selected environment/mint mode cannot safely create memberships."""


class BlockchainService:
    """Service for blockchain and Web3 operations"""

    @staticmethod
    async def mint_sbt(
        wallet_address: str, assurance_level: str, doc_hash: str
    ) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """
        Register a membership using the explicitly selected MINT_MODE.
        Returns: (success, token_id, tx_hash, error)
        """
        if not verify_eth_address(wallet_address):
            return (False, None, None, "Dirección de wallet inválida")

        if not doc_hash:
            return (False, None, None, "Document hash requerido")

        # Production remains fail-closed until membership minting consumes a
        # server-issued, one-time identity verification grant. SIWE proves
        # control of a wallet, not that the citizen completed identity checks.
        if settings.is_production:
            raise MintingUnavailable(
                "El minteo está bloqueado en producción hasta enlazar una "
                "verificación de identidad de un solo uso con esta wallet."
            )

        if settings.MINT_MODE == "disabled":
            raise MintingUnavailable(
                "La creación de membresías está deshabilitada en este entorno."
            )

        if settings.MINT_MODE == "onchain" and not chain_service.is_configured():
            raise MintingUnavailable(
                "El modo on-chain requiere SEPOLIA_RPC_URL, SBT_CONTRACT_ADDRESS "
                "y MINTER_PRIVATE_KEY."
            )

        try:
            address = wallet_address.lower()

            existing = await members_collection().find_one({"wallet_address": address})
            if existing:
                status = existing.get("status", "active")
                if status == "pending":
                    return (
                        False,
                        None,
                        None,
                        "Hay una transacción pendiente para esta wallet. Espera unos momentos.",
                    )
                elif status == "failed":
                    # Clean up failed previous attempt
                    await members_collection().delete_one({"wallet_address": address})
                else:
                    return (
                        False,
                        None,
                        None,
                        f"Ya existe un SBT para esta wallet (Token #{existing.get('token_id')})",
                    )

            # Insert "pending" record BEFORE interacting with the blockchain (P-23)
            member = Member(
                wallet_address=address,
                token_id=None,
                doc_hash=doc_hash,
                assurance_level=assurance_level,
                issuance_mode=(
                    "onchain" if settings.MINT_MODE == "onchain" else "demo"
                ),
                status="pending",
                identity_verified=False,
            )

            try:
                await members_collection().insert_one(member.model_dump())
            except DuplicateKeyError:
                return (False, None, None, "Ya existe un SBT para esta wallet")

            if settings.MINT_MODE == "onchain":
                try:
                    identity_hash_hex = document_identity_hash_hex(doc_hash)
                    tx_hash, onchain_token_id = await asyncio.to_thread(
                        chain_service.mint_sbt_onchain,
                        wallet_address=address,
                        identity_hash_hex=identity_hash_hex,
                        assurance_level=assurance_level,
                    )
                    if onchain_token_id is None:
                        raise MintingUnavailable(
                            "El minteo on-chain no devolvió un tokenId verificable."
                        )

                    token_id = onchain_token_id
                    await members_collection().update_one(
                        {"wallet_address": address},
                        {
                            "$set": {
                                "status": "active",
                                "token_id": token_id,
                                "tx_hash": tx_hash,
                            }
                        },
                    )
                    logger.info(
                        f"Membership minted on-chain: Token #{token_id} "
                        f"for {address} (tx {tx_hash})"
                    )
                    return (True, token_id, tx_hash, None)

                except Exception as e:
                    logger.error(f"On-chain mint failed for {address}: {e}")
                    await members_collection().update_one(
                        {"wallet_address": address}, {"$set": {"status": "failed"}}
                    )
                    if isinstance(e, MintingUnavailable):
                        raise
                    return (
                        False,
                        None,
                        None,
                        "No se pudo confirmar el minteo on-chain. Intenta más tarde.",
                    )
            else:
                # Demo mode
                last = await members_collection().find_one(
                    {"token_id": {"$ne": None}}, sort=[("token_id", -1)]
                )
                token_id = (last["token_id"] + 1) if last else 1

                await members_collection().update_one(
                    {"wallet_address": address},
                    {"$set": {"status": "active", "token_id": token_id}},
                )
                logger.info(
                    f"Membership registered (off-chain demo): Token #{token_id} for {address}"
                )
                return (True, token_id, None, None)

        except MintingUnavailable:
            # Reaches the router as a 503 with its specific reason instead of
            # being flattened into a generic "no se pudo crear la membresía".
            raise
        except Exception as e:
            logger.error(f"SBT minting error: {e}")
            return (False, None, None, "No se pudo crear la membresía.")

    @staticmethod
    async def get_member_by_wallet(wallet_address: str) -> Optional[Member]:
        """Get member by wallet address"""
        try:
            result = await members_collection().find_one(
                {"wallet_address": wallet_address.lower()}
            )
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
            return await members_collection().count_documents(
                {"created_at": {"$gte": cutoff}}
            )
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
                {
                    "$set": {
                        "status": "revoked",
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            # matched_count, not modified_count: revoking an already-revoked
            # token modifies nothing, and reporting that as "Token no
            # encontrado" would tell an operator the membership does not
            # exist while it is sitting in the collection, revoked.
            if result.matched_count == 0:
                return (False, "Token no encontrado")

            if result.modified_count == 0:
                logger.info(f"Membership already revoked: Token #{token_id}")
                return (True, None)

            logger.info(f"Membership revoked: Token #{token_id}")
            return (True, None)

        except Exception as e:
            # Never reflect the driver's error text to the caller.
            logger.error(f"Revocation error for token #{token_id}: {e}")
            return (False, "No se pudo revocar la membresía.")


# Singleton instance
blockchain_service = BlockchainService()
