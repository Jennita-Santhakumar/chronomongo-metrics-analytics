"""Bulk-seed the events time-series collection with synthetic data.

Resumable: progress is checkpointed (by completed hour-block, not raw count)
in a `seed_progress` collection so a restarted run continues from where it
left off instead of duplicating data. Run inside the api container so it
talks to the compose-network mongo host:

    docker compose exec api python -m scripts.seed_data --total 50000000

Data is generated and inserted in chronological order (oldest hour first),
one hour-block at a time. This matters a lot for time-series collections:
MongoDB buckets measurements by (meta, time range), and a hot/open bucket
gets appended to cheaply, but writing timestamps in random order across the
whole TTL window forces MongoDB to keep reopening buckets scattered across
the full 90-day span, and insert throughput degrades badly as the collection
grows (observed live: ~6.5k docs/sec at first, falling under 1k docs/sec by
~5M documents with randomly-ordered timestamps). Writing hour-by-hour, like
a real ingestion pipeline would, keeps each hour's buckets hot and closes
them for good before moving on.
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
INSERT_BATCH_SIZE = 10_000
SPAN_DAYS = 89  # stay inside the 90-day TTL window
SPAN_HOURS = SPAN_DAYS * 24


def random_event(ts: datetime) -> dict:
    event_type = random.choices(EVENT_TYPES, EVENT_WEIGHTS)[0]
    user_id = f"user_{random.randint(1, NUM_USERS)}"

    if event_type == "purchase":
        value = max(0.0, random.gauss(80, 40))
    elif event_type == "click":
        value = max(0.0, random.gauss(1, 0.5))
    else:
        value = max(0.0, random.gauss(5, 3))

    return {
        "timestamp": ts,
        "meta": {"event_type": event_type, "user_id": user_id},
        "value": round(value, 2),
    }


def hour_events(hour_start: datetime, count: int) -> list[dict]:
    events = [
        random_event(hour_start + timedelta(seconds=random.uniform(0, 3600)))
        for _ in range(count)
    ]
    events.sort(key=lambda e: e["timestamp"])
    return events


async def get_checkpoint(progress_coll) -> int:
    doc = await progress_coll.find_one({"_id": "seed"})
    return doc["completed_hours"] if doc else 0


async def set_checkpoint(progress_coll, completed_hours: int) -> None:
    await progress_coll.update_one(
        {"_id": "seed"}, {"$set": {"completed_hours": completed_hours}}, upsert=True
    )


async def seed(total: int) -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    events = db["events"]
    progress = db["seed_progress"]

    docs_per_hour = total // SPAN_HOURS
    remainder = total - docs_per_hour * SPAN_HOURS

    start_hour = await get_checkpoint(progress)
    if start_hour >= SPAN_HOURS:
        logger.info("Already seeded all %d hour-blocks, nothing to do", SPAN_HOURS)
        return

    logger.info(
        "Resuming from hour-block %d/%d, ~%d docs/hour, seeding up to %d total documents",
        start_hour,
        SPAN_HOURS,
        docs_per_hour,
        total,
    )

    now = datetime.now(timezone.utc)
    span_start = now - timedelta(hours=SPAN_HOURS)

    inserted_this_run = 0
    start = time.monotonic()

    for hour_idx in range(start_hour, SPAN_HOURS):
        hour_start = span_start + timedelta(hours=hour_idx)
        count = docs_per_hour + (remainder if hour_idx == SPAN_HOURS - 1 else 0)
        batch = hour_events(hour_start, count)

        chunks = [
            batch[i : i + INSERT_BATCH_SIZE] for i in range(0, len(batch), INSERT_BATCH_SIZE)
        ]
        await asyncio.gather(
            *(events.insert_many(chunk, ordered=False) for chunk in chunks)
        )

        inserted_this_run += count
        await set_checkpoint(progress, hour_idx + 1)

        elapsed = time.monotonic() - start
        rate = inserted_this_run / elapsed if elapsed > 0 else 0
        if hour_idx % 24 == 0 or hour_idx == SPAN_HOURS - 1:
            logger.info(
                "Completed hour-block %d/%d (~%d docs so far this run, %.0f docs/sec, %.1f min elapsed)",
                hour_idx + 1,
                SPAN_HOURS,
                inserted_this_run,
                rate,
                elapsed / 60,
            )

    logger.info(
        "Done. Seeded all %d hour-blocks (~%d total documents) in %.1f min",
        SPAN_HOURS,
        total,
        (time.monotonic() - start) / 60,
    )
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=50_000_000)
    args = parser.parse_args()
    asyncio.run(seed(args.total))
