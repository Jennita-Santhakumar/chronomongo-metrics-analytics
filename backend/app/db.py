import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongo_db]


async def init_db(db: AsyncIOMotorDatabase | None = None) -> None:
    """Create the time-series collection (with TTL) and supporting indexes if missing."""
    if db is None:
        db = get_db()

    try:
        await db.create_collection(
            "events",
            timeseries={
                "timeField": "timestamp",
                "metaField": "meta",
                "granularity": "seconds",
            },
            expireAfterSeconds=settings.ttl_seconds,
        )
        logger.info("Created 'events' time-series collection")
    except CollectionInvalid:
        pass  # already exists

    events = db["events"]
    await events.create_index([("meta.user_id", 1), ("timestamp", -1)])
    await events.create_index([("timestamp", 1), ("meta.event_type", 1)])
