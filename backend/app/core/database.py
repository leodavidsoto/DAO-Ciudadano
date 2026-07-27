"""
Database Module
MongoDB connection and utilities
"""
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

# How long a request waits for a reachable server before giving up. The driver
# default (30s) makes every request hang on a sleeping or misconfigured
# database; on a free tier with cold starts that reads as a total outage.
SERVER_SELECTION_TIMEOUT_MS = 8000

# Backoff for the background index builder. Transient unavailability (a cold
# Atlas cluster) must not be treated like a data problem.
INDEX_RETRY_DELAYS_S = [1, 3, 8, 20, 45]

# MongoDB error code for a unique-constraint violation.
DUPLICATE_KEY_CODE = 11000


class Database:
    """Database connection manager"""
    
    client: Optional[AsyncIOMotorClient] = None
    _index_task: Optional[asyncio.Task] = None

    # Integrity state. Startup does not block on index creation (a cold free-tier
    # cluster would turn a slow first request into a failed deploy), but writes
    # that depend on a missing unique index are refused until it exists.
    _missing_required_indexes: list = []
    _index_error: Optional[str] = None
    _indexes_ready: bool = False
    
    @classmethod
    def connect(cls, mongo_url: str, db_name: str):
        """Initialize database connection"""
        cls.client = AsyncIOMotorClient(
            mongo_url,
            serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
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
    
    @classmethod
    def get_db(cls):
        """Get database instance"""
        if cls.client is None:
            raise RuntimeError("Database not initialized. Call connect() first.")
        return cls.db

    # (collection, keys, unique, required)
    # `required=True`: without this index the data model can be corrupted
    # silently — double votes, duplicate token_ids, duplicated representatives.
    INDEX_SPECS = [
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

    @classmethod
    def schedule_index_creation(cls):
        """Build indexes in the background; never block startup.

        Awaiting index creation during startup means serving no traffic until
        the database answers. On a free tier that already pays a cold start on
        every wake-up, that turns a slow first request into a failed deploy.

        The trade-off is handled by `integrity_ready()`: the process starts,
        but mutating endpoints refuse to write while a required unique index
        is missing (audit finding N-7).
        """
        cls._index_task = asyncio.create_task(cls._build_indexes_with_retry())
        return cls._index_task

    @classmethod
    async def _build_indexes_with_retry(cls):
        """Retry only what is worth retrying.

        Two failure causes look alike in the logs and are not alike at all:

        - transient (cluster asleep, network blip): retry with backoff, the
          service stays up and becomes healthy on its own.
        - data violation (duplicate key 11000): a document already breaks the
          invariant. Retrying will never fix it; the collection stays
          unprotected and writes to it must be refused until someone cleans
          the duplicates.
        """
        for delay in [0] + INDEX_RETRY_DELAYS_S:
            if delay:
                await asyncio.sleep(delay)

            missing, permanent, error = await cls._create_indexes_once()
            cls._missing_required_indexes = missing
            cls._index_error = error

            if not missing:
                cls._indexes_ready = True
                logger.info("All required integrity indexes are in place")
                return

            if permanent:
                logger.error(
                    "Integrity indexes cannot be created — duplicate documents "
                    f"already violate the constraint: {missing}. Writes to these "
                    "collections are refused until the duplicates are removed."
                )
                return

            logger.warning(f"Indexes not ready yet ({error}); retrying in {delay}s")

        logger.error(f"Gave up creating indexes: {cls._missing_required_indexes}")

    @classmethod
    async def _create_indexes_once(cls):
        """Create every index independently.

        A failure on one must not skip the rest (audit finding N-7): the
        election indexes are the real concurrency protection and used to be
        silently skipped when the first index failed.

        Returns (missing_required, permanent, last_error).
        """
        missing = []
        permanent = False
        last_error = None

        for collection, keys, unique, required in cls.INDEX_SPECS:
            try:
                await cls.get_db()[collection].create_index(keys, unique=unique)
            except Exception as e:
                label = f"{collection}.{keys}"
                last_error = str(e)
                if getattr(e, "code", None) == DUPLICATE_KEY_CODE:
                    permanent = True
                if required:
                    missing.append(label)
                    logger.error(f"Required index missing: {label} — {e}")
                else:
                    logger.warning(f"Optional index not created: {label} — {e}")

        return missing, permanent, last_error

    @classmethod
    async def ensure_indexes(cls):
        """Create indexes and wait for the result. Used by tests."""
        await cls._build_indexes_with_retry()

    @classmethod
    def integrity_ready(cls) -> bool:
        """True when every required unique index exists."""
        return cls._indexes_ready and not cls._missing_required_indexes

    @classmethod
    def integrity_status(cls) -> dict:
        """Diagnostics for /health."""
        return {
            "ready": cls.integrity_ready(),
            "missing_required_indexes": list(cls._missing_required_indexes),
            "error": cls._index_error,
        }


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

