"""
Blockchain Service
Handles Web3 operations, wallet connections, and SBT minting

`MINT_MODE` gobierna ÚNICAMENTE el registro local: `disabled` o `demo` (solo
Mongo). El minteo real vive en `/membership/mint-zk`, porque el contrato actual
solo emite contra una prueba Groth16 y este endpoint no la tiene.

`MINT_MODE=onchain` se rechaza explícitamente. Antes intentaba llamar a
`mintMembership(to, identityHash, assuranceLevel, uri)`, una firma que dejó de
existir al migrar al modelo ZK: el resultado era siempre un fallo genérico
("no se pudo confirmar el minteo on-chain") que parecía un problema de red.
Falla con su motivo real en vez de aparentar un camino que no existe.

Producción sigue bloqueada aquí, pero el motivo ya NO es la identidad: desde
ROADMAP 1.10 el alta consume un `membership_grant` firmado por el servidor, así
que la persona sí está verificada. Lo que falta es el efecto on-chain — este
endpoint solo escribe en Mongo, y una membresía que no existe en el contrato no
es una membresía de la DAO. El camino real es `/membership/mint-zk`.
"""

from typing import Optional, Tuple
import logging
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from ..core.config import settings
from ..core.database import members_collection
from ..core.security_middleware import verify_eth_address
from ..models import Member

logger = logging.getLogger(__name__)


class MintingUnavailable(RuntimeError):
    """The selected environment/mint mode cannot safely create memberships."""


class BlockchainService:
    """Service for blockchain and Web3 operations"""

    @staticmethod
    def ensure_minting_available() -> None:
        """¿Puede este despliegue dar altas por esta vía? Si no, dice por qué.

        Separado de `mint_sbt` para que el router pueda preguntarlo ANTES de
        quemar el grant de identidad: gastar una verificación civil por una
        variable de entorno mal puesta obligaría a la persona a repetir todo
        el flujo por un problema que no es suyo.
        """
        # Producción sigue cerrada, pero ya no por la identidad —el alta
        # consume un grant firmado por el servidor (ROADMAP 1.10)—, sino
        # porque esta vía no llega al contrato. Una membresía solo en Mongo
        # no la reconoce la cadena.
        if settings.is_production:
            raise MintingUnavailable(
                "Esta vía de alta solo registra la membresía en la base de "
                "datos y no la emite on-chain, así que está bloqueada en "
                "producción. Usa POST /api/membership/mint-zk."
            )

        if settings.MINT_MODE == "disabled":
            raise MintingUnavailable(
                "La creación de membresías está deshabilitada en este entorno."
            )

        if settings.MINT_MODE == "onchain":
            raise MintingUnavailable(
                "Este endpoint no puede mintear on-chain: el contrato actual "
                "solo emite contra una prueba Groth16. Usa "
                "POST /api/membership/mint-zk."
            )

    @staticmethod
    async def mint_sbt(
        wallet_address: str, assurance_level: str, doc_hash: str
    ) -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
        """
        Register a membership using the explicitly selected MINT_MODE.

        `assurance_level` y `doc_hash` vienen del `membership_grant` que el
        servidor firmó, NUNCA del cuerpo de la petición (AUDIT P-4). El router
        es quien lo garantiza.

        Returns: (success, token_id, tx_hash, error)
        """
        if not verify_eth_address(wallet_address):
            return (False, None, None, "Dirección de wallet inválida")

        if not doc_hash:
            return (False, None, None, "Document hash requerido")

        # Se repite la comprobación del router: este método es público y un
        # llamador nuevo no debe poder saltarse el cierre por entorno.
        BlockchainService.ensure_minting_available()

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
            # `identity_verified` sigue en False aunque el grant sea real, y no
            # es un descuido: fuera de producción el proveedor civil puede ser
            # un simulador, y esta bandera es lo que decide si una fila
            # sobrevive a que la misma base se promueva a producción. Solo la
            # vía ZK puede ponerla en True, porque allí la garantía la impone
            # el contrato y no una variable de entorno.
            member = Member(
                wallet_address=address,
                token_id=None,
                doc_hash=doc_hash,
                assurance_level=assurance_level,
                issuance_mode="demo",
                status="pending",
                identity_verified=False,
            )

            try:
                await members_collection().insert_one(member.model_dump())
            except DuplicateKeyError:
                return (False, None, None, "Ya existe un SBT para esta wallet")

            # Demo mode: el único que llega aquí. `tx_hash` se queda en None a
            # propósito — no hay transacción, y fabricar una sería exactamente
            # el dato inventado que este repositorio ya quitó una vez.
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
