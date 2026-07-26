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

        The unique index on members.wallet_address is what actually prevents
        two memberships for the same wallet under concurrency (ROADMAP 1.11).
        """
        try:
            await cls.get_db()["members"].create_index("wallet_address", unique=True)
            await cls.get_db()["members"].create_index("token_id")
        except Exception as e:
            # A pre-existing duplicate in the collection blocks unique index
            # creation; keep the app bootable and surface it in the logs.
            logger.warning(f"Could not create members indexes: {e}")


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

