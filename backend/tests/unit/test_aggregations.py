from app.aggregations import (
    build_cohort_pipeline,
    build_hourly_pipeline,
    build_percentile_pipeline,
)


def test_hourly_pipeline_filters_event_type_and_window():
    pipeline = build_hourly_pipeline("click", hours=6)
    match_stage = pipeline[0]["$match"]
    assert match_stage["meta.event_type"] == "click"
    assert "$gte" in match_stage["timestamp"]


def test_hourly_pipeline_groups_by_hour_and_sorts():
    pipeline = build_hourly_pipeline("click", hours=6)
    group_stage = pipeline[1]["$group"]
    assert group_stage["_id"]["$dateToString"]["format"] == "%Y-%m-%d %H:00"
    assert pipeline[2] == {"$sort": {"_id": 1}}


def test_percentile_pipeline_converts_percent_to_fraction():
    pipeline = build_percentile_pipeline("purchase", [50, 95, 99])
    percentile_spec = pipeline[1]["$group"]["values"]["$percentile"]
    assert percentile_spec["p"] == [0.5, 0.95, 0.99]
    assert percentile_spec["method"] == "approximate"


def test_cohort_pipeline_has_three_facets():
    pipeline = build_cohort_pipeline(days=30)
    facets = pipeline[1]["$facet"]
    assert set(facets.keys()) == {"new_users", "retention", "engagement"}


def test_cohort_engagement_bucket_boundaries():
    pipeline = build_cohort_pipeline(days=30)
    bucket_stage = pipeline[1]["$facet"]["engagement"][1]["$bucket"]
    assert bucket_stage["boundaries"] == [1, 5, 10, 50, 100]
    assert bucket_stage["default"] == "100+"
