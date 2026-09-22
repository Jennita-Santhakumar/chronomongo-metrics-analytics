"""Pure pipeline builders (unit-testable without a live database) plus the
async service that runs them against Motor."""

from datetime import datetime, timedelta, timezone


def build_hourly_pipeline(event_type: str, hours: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [
        {"$match": {"meta.event_type": event_type, "timestamp": {"$gte": since}}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d %H:00", "date": "$timestamp"}
                },
                "count": {"$sum": 1},
                "avg_value": {"$avg": "$value"},
                "max_value": {"$max": "$value"},
                "min_value": {"$min": "$value"},
            }
        },
        {"$sort": {"_id": 1}},
    ]


def build_percentile_pipeline(event_type: str, percentiles: list[int]) -> list[dict]:
    ps = [p / 100 for p in percentiles]
    return [
        {"$match": {"meta.event_type": event_type}},
        {
            "$group": {
                "_id": None,
                "values": {
                    "$percentile": {
                        "input": "$value",
                        "p": ps,
                        "method": "approximate",
                    }
                },
            }
        },
    ]


def build_cohort_pipeline(days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return [
        {"$match": {"timestamp": {"$gte": since}}},
        {
            "$facet": {
                "new_users": [
                    {
                        "$group": {
                            "_id": {
                                "$dateToString": {
                                    "format": "%Y-%m-%d",
                                    "date": "$timestamp",
                                }
                            },
                            "count": {"$sum": 1},
                        }
                    },
                    {"$sort": {"_id": 1}},
                ],
                "retention": [
                    {
                        "$group": {
                            "_id": "$meta.user_id",
                            "first_seen": {"$min": "$timestamp"},
                            "last_seen": {"$max": "$timestamp"},
                            "total_events": {"$sum": 1},
                        }
                    }
                ],
                "engagement": [
                    {
                        "$group": {
                            "_id": "$meta.user_id",
                            "event_count": {"$sum": 1},
                        }
                    },
                    {
                        "$bucket": {
                            "groupBy": "$event_count",
                            "boundaries": [1, 5, 10, 50, 100],
                            "default": "100+",
                        }
                    },
                ],
            }
        },
    ]


class AnalyticsService:
    def __init__(self, db):
        self.events = db["events"]

    async def get_hourly_stats(self, event_type: str, hours: int = 24) -> list[dict]:
        pipeline = build_hourly_pipeline(event_type, hours)
        return await self.events.aggregate(pipeline).to_list(length=None)

    async def get_percentiles(
        self, event_type: str, percentiles: list[int] | None = None
    ) -> dict[str, float]:
        percentiles = percentiles or [50, 75, 95, 99]
        pipeline = build_percentile_pipeline(event_type, percentiles)
        result = await self.events.aggregate(pipeline).to_list(length=1)
        if not result:
            return {}
        values = result[0]["values"]
        return {f"p{p}": v for p, v in zip(percentiles, values)}

    async def get_cohort_analysis(self, days: int = 30) -> dict:
        pipeline = build_cohort_pipeline(days)
        result = await self.events.aggregate(pipeline).to_list(length=1)
        return result[0] if result else {"new_users": [], "retention": [], "engagement": []}
