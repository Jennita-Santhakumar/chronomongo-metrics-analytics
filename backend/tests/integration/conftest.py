import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.db import init_db

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")


@pytest.fixture
async def db():
    client = AsyncIOMotorClient(MONGO_URI)
    db_name = f"test_{uuid.uuid4().hex[:8]}"
    database = client[db_name]
    await init_db(database)
    yield database
    await client.drop_database(db_name)
    client.close()
