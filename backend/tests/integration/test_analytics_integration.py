from datetime import datetime, timedelta, timezone

import pytest

from app.aggregations import AnalyticsService

pytestmark = pytest.mark.asyncio


async def _insert_events(db, n: int, event_type: str, user_id: str, base_value: float):
    now = datetime.now(timezone.utc)
    docs = [
        {
            "timestamp": now - timedelta(minutes=i),
            "meta": {"event_type": event_type, "user_id": user_id},
            "value": base_value + i,
        }
        for i in range(n)
    ]
    await db["events"].insert_many(docs)


async def test_hourly_stats_aggregates_counts(db):
    await _insert_events(db, 10, "click", "user_1", 1.0)
    service = AnalyticsService(db)

    stats = await service.get_hourly_stats("click", hours=24)

    assert sum(s["count"] for s in stats) == 10


async def test_percentiles_returns_expected_keys(db):
    await _insert_events(db, 100, "purchase", "user_1", 0.0)
    service = AnalyticsService(db)

    result = await service.get_percentiles("purchase", [50, 95, 99])

    assert set(result.keys()) == {"p50", "p95", "p99"}
    assert result["p50"] < result["p99"]


async def test_cohort_analysis_counts_distinct_users(db):
    await _insert_events(db, 5, "page_view", "user_a", 1.0)
    await _insert_events(db, 3, "page_view", "user_b", 1.0)
    service = AnalyticsService(db)

    result = await service.get_cohort_analysis(days=30)

    retained_users = {r["_id"] for r in result["retention"]}
    assert retained_users == {"user_a", "user_b"}
