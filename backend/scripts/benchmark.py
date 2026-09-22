"""Benchmark the analytics aggregation pipelines with and without the
secondary indexes, against whatever is currently seeded in `events`.

Writes real measured numbers (no fabrication) to benchmark_results.md/json.

    docker compose exec api python -m scripts.benchmark
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

from app.aggregations import (
    build_cohort_pipeline,
    build_hourly_pipeline,
    build_percentile_pipeline,
)
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("benchmark")

INDEXES = [
    ("meta.user_id_1_timestamp_-1", [("meta.user_id", 1), ("timestamp", -1)]),
    ("timestamp_1_meta.event_type_1", [("timestamp", 1), ("meta.event_type", 1)]),
]


async def timed(coro_factory) -> float:
    start = time.perf_counter()
    await coro_factory()
    return time.perf_counter() - start


async def run_suite(events, label: str) -> dict:
    results = {}

    results["hourly"] = await timed(
        lambda: events.aggregate(build_hourly_pipeline("page_view", 24)).to_list(length=None)
    )
    results["percentiles"] = await timed(
        lambda: events.aggregate(build_percentile_pipeline("purchase", [50, 95, 99])).to_list(length=1)
    )
    results["cohort"] = await timed(
        lambda: events.aggregate(build_cohort_pipeline(7)).to_list(length=1)
    )

    logger.info("[%s] %s", label, {k: f"{v:.3f}s" for k, v in results.items()})
    return results


async def main() -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    events = db["events"]

    doc_count = await events.estimated_document_count()
    logger.info("Benchmarking against %d documents", doc_count)

    logger.info("Dropping secondary indexes for baseline run...")
    for name, _ in INDEXES:
        try:
            await events.drop_index(name)
        except Exception:
            pass

    baseline = await run_suite(events, "no secondary indexes")

    logger.info("Recreating secondary indexes...")
    for _, spec in INDEXES:
        await events.create_index(spec)

    optimized = await run_suite(events, "with secondary indexes")

    speedups = {
        k: round(baseline[k] / optimized[k], 2) if optimized[k] > 0 else None
        for k in baseline
    }

    report = {
        "document_count": doc_count,
        "baseline_seconds": baseline,
        "optimized_seconds": optimized,
        "speedup_x": speedups,
    }

    out_json = Path(__file__).resolve().parent.parent / "benchmark_results.json"
    out_json.write_text(json.dumps(report, indent=2))

    out_md = Path(__file__).resolve().parent.parent / "benchmark_results.md"
    lines = [
        "# Benchmark Results",
        "",
        f"Measured against **{doc_count:,}** documents in the `events` collection.",
        "",
        "| Query | No secondary indexes | With secondary indexes | Speedup |",
        "|---|---|---|---|",
    ]
    for k in baseline:
        lines.append(
            f"| {k} | {baseline[k]:.3f}s | {optimized[k]:.3f}s | {speedups[k]}x |"
        )
    out_md.write_text("\n".join(lines) + "\n")

    logger.info("Wrote %s and %s", out_json, out_md)
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
