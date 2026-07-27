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
    
    @classmethod
    def connect(cls, mongo_url: str, db_name: str):
        """Initialize database connection"""
        cls.client = AsyncIOMotorClient(mongo_url)
        cls.db = cls.client[db_name]
        logger.info(f"Connected to MongoDB database: {db_name}")
        return cls.db
    
    @classmethod
    def close(cls):
        """Close database connection"""
        if cls.client:
            cls.client.close()
            logger.info("Disconnected from MongoDB")
    
    @classmethod
    def get_db(cls):
        """Get database instance"""
        if cls.client is None:
            raise RuntimeError("Database not initialized. Call connect() first.")
        return cls.db

    @classmethod
    async def ensure_indexes(cls):
        """Create the indexes the application relies on (idempotent).

        Each index is created independently: a failure on one must not skip
        the rest (audit finding N-7). A pre-existing duplicate blocks unique
        index creation, and the indexes below are the *only* thing preventing
        double memberships, double votes and duplicated representatives under
        concurrency — so the ones marked required abort startup instead of
        letting the service run without its integrity invariants.
        """
        # (collection, keys, unique, required)
        # `required=True` means: without this index the data model can be
        # corrupted silently, so refuse to start.
        specs = [
            ("members", "wallet_address", True, True),
            ("members", "token_id", True, True),
            ("votes", [("proposal_id", 1), ("voter_address", 1)], True, True),
            ("candidacies", [("election_id", 1), ("candidate_address", 1)], True, True),
            ("election_votes", [("election_id", 1), ("voter_address", 1)], True, True),
            ("representatives", [("election_id", 1), ("address", 1)], True, True),
            ("delegations", "delegator", True, True),
            ("delegations", "delegate", False, False),
            ("proposals", "id", True, False),
            ("elections", "id", True, False),
        ]

        failed_required = []
        for collection, keys, unique, required in specs:
            try:
                await cls.get_db()[collection].create_index(keys, unique=unique)
            except Exception as e:
                label = f"{collection}.{keys}"
                if required:
                    logger.error(f"Required index missing: {label} — {e}")
                    failed_required.append(label)
                else:
                    logger.warning(f"Optional index not created: {label} — {e}")

        if failed_required:
            raise RuntimeError(
                "No se pudieron crear índices de integridad obligatorios: "
                + ", ".join(failed_required)
                + ". Suele deberse a documentos duplicados preexistentes; "
                "audítalos y elimínalos antes de arrancar."
            )


# Collections helpers
def get_collection(name: str):
    """Get a collection by name"""
    return Database.get_db()[name]


# Convenience accessors
def members_collection():
    return get_collection("members")


def identity_events_collection():
    return get_collection("identity_events")


def status_checks_collection():
    return get_collection("status_checks")


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

