import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from backend.config import settings

logger = logging.getLogger(__name__)
client: AsyncIOMotorClient | None = None
database: AsyncIOMotorDatabase | None = None


async def connect_to_mongo() -> None:
    """Create the async Mongo client, verify it, and prepare application indexes."""
    global client, database

    if client is not None:
        return

    candidate = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    try:
        await candidate.admin.command("ping")
        db = candidate[settings.mongodb_db_name]
        await db["migrations"].create_index("name", unique=True)
        await db["projects"].create_index("created_at")
    except Exception:
        candidate.close()
        logger.exception("Unable to initialize MongoDB connection")
        raise

    client = candidate
    database = db
    logger.info("Connected to MongoDB database '%s'", settings.mongodb_db_name)


async def close_mongo_connection() -> None:
    """Close the Motor client safely during application shutdown."""
    global client, database
    if client is not None:
        client.close()
        client = None
        database = None
        logger.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    if database is None:
        raise RuntimeError("MongoDB is not initialized; call connect_to_mongo() first")
    return database


def get_migrations_collection() -> AsyncIOMotorCollection:
    return get_database()["migrations"]


def get_projects_collection() -> AsyncIOMotorCollection:
    return get_database()["projects"]


async def check_mongo_connection() -> bool:
    """Ping MongoDB and return False for absent or unhealthy connections."""
    if client is None:
        return False
    try:
        result: dict[str, Any] = await client.admin.command("ping")
        return result.get("ok") == 1.0
    except Exception:
        logger.warning("MongoDB health check failed", exc_info=True)
        return False
