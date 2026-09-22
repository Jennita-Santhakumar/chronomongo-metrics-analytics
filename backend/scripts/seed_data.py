"""Bulk-seed the events time-series collection with synthetic data.

Resumable: progress is checkpointed in a `seed_progress` collection so a
restarted run continues from where it left off instead of duplicating data.
Run inside the api container so it talks to the compose-network mongo host:

    docker compose exec api python -m scripts.seed_data --total 50000000
"""

import argparse
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("seed")

EVENT_TYPES = ["page_view", "click", "purchase"]
EVENT_WEIGHTS = [0.70, 0.25, 0.05]
NUM_USERS = 200_000
BATCH_SIZE = 10_000
SPAN_DAYS = 89  # stay inside the 90-day TTL window


def random_event(now: datetime) -> dict:
    event_type = random.choices(EVENT_TYPES, EVENT_WEIGHTS)[0]
    user_id = f"user_{random.randint(1, NUM_USERS)}"
    offset = timedelta(
        days=random.uniform(0, SPAN_DAYS),
        seconds=random.uniform(0, 86400),
    )
    if event_type == "purchase":
        value = max(0.0, random.gauss(80, 40))
    elif event_type == "click":
        value = max(0.0, random.gauss(1, 0.5))
    else:
        value = max(0.0, random.gauss(5, 3))

    return {
        "timestamp": now - offset,
        "meta": {"event_type": event_type, "user_id": user_id},
        "value": round(value, 2),
    }


async def get_checkpoint(progress_coll) -> int:
    doc = await progress_coll.find_one({"_id": "seed"})
    return doc["inserted"] if doc else 0


async def set_checkpoint(progress_coll, inserted: int) -> None:
    await progress_coll.update_one(
        {"_id": "seed"}, {"$set": {"inserted": inserted}}, upsert=True
    )


async def seed(total: int) -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    events = db["events"]
    progress = db["seed_progress"]

    already = await get_checkpoint(progress)
    if already >= total:
        logger.info("Already seeded %d/%d documents, nothing to do", already, total)
        return

    logger.info("Resuming from %d, seeding up to %d documents", already, total)
    now = datetime.now(timezone.utc)
    inserted = already
    start = time.monotonic()

    while inserted < total:
        batch_size = min(BATCH_SIZE, total - inserted)
        batch = [random_event(now) for _ in range(batch_size)]
        await events.insert_many(batch, ordered=False)
        inserted += batch_size
        await set_checkpoint(progress, inserted)

        elapsed = time.monotonic() - start
        rate = (inserted - already) / elapsed if elapsed > 0 else 0
        if inserted % (BATCH_SIZE * 10) == 0 or inserted >= total:
            logger.info(
                "Inserted %d/%d (%.0f docs/sec, %.1f min elapsed)",
                inserted,
                total,
                rate,
                elapsed / 60,
            )

    logger.info("Done. Seeded %d total documents in %.1f min", total, (time.monotonic() - start) / 60)
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=50_000_000)
    args = parser.parse_args()
    asyncio.run(seed(args.total))
