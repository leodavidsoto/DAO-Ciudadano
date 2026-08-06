"""
Database Module
MongoDB connection and utilities
"""

from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Database:
    """Database connection manager"""

    client: Optional[AsyncIOMotorClient] = None
    db = None
    indexes_ready: bool = False

    # The driver default is 30 s. With a wrong MONGO_URL that turns startup
    # into a 30 s stall on the first index call before the app becomes
    # reachable at all; 5 s still tolerates an Atlas cold start while making
    # a misconfiguration visible in the logs almost immediately.
    SERVER_SELECTION_TIMEOUT_MS = 5000

    @classmethod
    def connect(cls, mongo_url: str, db_name: str):
        """Initialize database connection"""
        cls.indexes_ready = False
        cls.client = AsyncIOMotorClient(
            mongo_url,
            serverSelectionTimeoutMS=cls.SERVER_SELECTION_TIMEOUT_MS,
        )
        cls.db = cls.client[db_name]
        logger.info(f"Connected to MongoDB database: {db_name}")
        return cls.db

    @classmethod
    def close(cls):
        """Close database connection"""
        if cls.client:
            cls.client.close()
            logger.info("Disconnected from MongoDB")
        cls.indexes_ready = False

    @classmethod
    def get_db(cls):
        """Get database instance"""
        if cls.client is None:
            raise RuntimeError("Database not initialized. Call connect() first.")
        return cls.db

    @classmethod
    async def ensure_indexes(cls):
        """Create the indexes the application relies on (idempotent).

        The unique index on members.wallet_address is what actually prevents
        two memberships for the same wallet under concurrency (ROADMAP 1.11).
        """
        cls.indexes_ready = False
        try:
            await cls.get_db()["members"].create_index("wallet_address", unique=True)
            await cls.get_db()["members"].create_index("token_id", unique=True)
            # ROADMAP 1.11 — unicidad por PERSONA, no solo por wallet.
            #
            # El índice de wallet_address impide dos membresías para la misma
            # wallet, pero nada impedía que la misma persona minteara con dos
            # wallets distintas. Desde D-2 el valor que identifica a una
            # persona es el nullifier del circuito: se deriva del secreto de
            # identidad y del scope del contrato, así que dos credenciales de
            # la misma persona en el mismo scope producen el MISMO nullifier
            # (y el contrato ya rechaza el segundo minteo por eso).
            #
            # Este índice replica esa regla en la base: sin él, un fallo de
            # reconciliación podía dejar dos filas activas para una persona.
            #
            # Parcial y no `sparse`: las filas demo/legacy tienen
            # nullifier_hash = None y varios `null` colisionarían en un índice
            # único normal, impidiendo incluso crearlo.
            await cls.get_db()["members"].create_index(
                "nullifier_hash",
                unique=True,
                partialFilterExpression={"nullifier_hash": {"$type": "string"}},
            )
            # Governance: the application-level "already voted" lookup gives
            # a friendly response, but only this compound unique index closes
            # the race between simultaneous requests from the same member.
            await cls.get_db()["votes"].create_index(
                [("proposal_id", 1), ("voter_address", 1)], unique=True
            )
            # Elections: one candidacy and one vote per member per election.
            # The unique indexes are what actually enforce this under
            # concurrency; the router checks only produce friendlier errors.
            await cls.get_db()["candidacies"].create_index(
                [("election_id", 1), ("candidate_address", 1)], unique=True
            )
            await cls.get_db()["election_votes"].create_index(
                [("election_id", 1), ("voter_address", 1)], unique=True
            )
            # Un escaño por (elección, persona). Es lo que hace converger a dos
            # finalizaciones simultáneas en vez de duplicar representantes, y
            # lo que permite que `finalize_election` sea un upsert idempotente
            # reejecutable tras una caída (ROADMAP 3.10).
            await cls.get_db()["representatives"].create_index(
                [("election_id", 1), ("address", 1)], unique=True
            )
            await cls.get_db()["delegations"].create_index("delegator", unique=True)
            await cls.get_db()["delegations"].create_index("delegate")
            # Índices ciegos de usuarios (app/core/identity.lookup_key): el
            # campo real (rut/email) va cifrado y no es determinístico, así
            # que la unicidad se aplica sobre estos, no sobre el valor cifrado.
            await cls.get_db()["users"].create_index("rut_key", unique=True)
            await cls.get_db()["users"].create_index("email_key", unique=True)
            # Sesiones SIWE: nonce de un solo uso.
            await cls.get_db()["siwe_nonces"].create_index("nonce", unique=True)
            # Papeletas EIP-712: un nonce no se puede reutilizar por votante.
            await cls.get_db()["ballot_nonces"].create_index(
                [("voter_address", 1), ("nonce", 1)], unique=True
            )
            # Árbol de identidades ZK (ADR-001, D-2): una hoja por sujeto. Este
            # índice es lo que impide que un reintento del cliente le emita dos
            # credenciales a la misma persona; la comprobación en el servicio
            # solo da un error más claro.
            await cls.get_db()["identity_commitments"].create_index(
                "subject_key", unique=True
            )
            await cls.get_db()["identity_commitments"].create_index(
                "commitment", unique=True
            )
            # Grants civiles: un digest solo existe una vez.
            await cls.get_db()["identity_grants"].create_index("digest", unique=True)
            # Idempotencia del relayer: un nullifier -> como mucho una tx.
            await cls.get_db()["mint_operations"].create_index(
                "nullifier_hash", unique=True
            )
            # Barrido de reconciliación: busca operaciones abiertas por
            # antigüedad. Sin este índice recorrería la colección entera cada
            # vez que se ejecuta.
            await cls.get_db()["mint_operations"].create_index(
                [("status", 1), ("created_at", 1)]
            )
            # MACI: una llave vigente por wallet. El historial NO es unico:
            # cambiar de llave es el mecanismo anti-coercion del protocolo.
            await cls.get_db()["maci_keys"].create_index("wallet_address", unique=True)
            await cls.get_db()["maci_key_history"].create_index(
                [("wallet_address", 1), ("version", 1)], unique=True
            )
            # ERC-4337: un nullifier -> como mucho una UserOperation.
            await cls.get_db()["erc4337_operations"].create_index(
                "nullifier_hash", unique=True
            )
            await cls.get_db()["erc4337_operations"].create_index(
                "operation_id", unique=True
            )
            # MACI: un state_index por wallet y consulta; idempotencia anónima
            # por (poll, idempotency_key) — nunca por wallet, que no se conoce.
            await cls.get_db()["maci_poll_registry"].create_index(
                [("poll_id", 1), ("wallet_address", 1)], unique=True, sparse=True
            )
            await cls.get_db()["maci_messages"].create_index(
                [("poll_id", 1), ("idempotency_key", 1)], unique=True, sparse=True
            )
            # Retención (ROADMAP 1.4): los TTL salen de la política declarada
            # en app/core/retention.py, no de números repartidos por aquí. Si
            # alguien cambia la política, el índice cambia con ella.
            from . import retention

            for rule in retention.automatic_rules():
                await cls.get_db()[rule.collection].create_index(
                    rule.field, expireAfterSeconds=rule.ttl_seconds
                )

            cls.indexes_ready = True
        except Exception as e:
            # A pre-existing duplicate in the collection blocks unique index
            # creation; keep the app bootable and surface it in the logs.
            logger.warning(f"Could not create required database indexes: {e}")


# Collections helpers
def get_collection(name: str):
    """Get a collection by name"""
    return Database.get_db()[name]


# Convenience accessors
def members_collection():
    return get_collection("members")


def users_collection():
    return get_collection("users")


def proposals_collection():
    return get_collection("proposals")


def votes_collection():
    return get_collection("votes")


def delegations_collection():
    return get_collection("delegations")


def treasury_transactions_collection():
    return get_collection("treasury_transactions")


def elections_collection():
    return get_collection("elections")


def candidacies_collection():
    return get_collection("candidacies")


def election_votes_collection():
    return get_collection("election_votes")


def representatives_collection():
    return get_collection("representatives")


def siwe_nonces_collection():
    return get_collection("siwe_nonces")


def ballot_nonces_collection():
    return get_collection("ballot_nonces")
