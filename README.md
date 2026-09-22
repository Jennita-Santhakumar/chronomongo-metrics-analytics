# MongoDB Time-Series Analytics Platform

An event analytics system built on MongoDB's time-series collections: complex aggregation pipelines (hourly rollups, percentile distributions, cohort/retention analysis), TTL-based auto-expiration, compound secondary indexes, and a live-updating dashboard. Backend is FastAPI + Motor (async), frontend is React + Recharts.

> **Note on scale**: the PRD's target is 50M+ documents. We seeded and benchmarked against **5,000,000** real documents instead — see [Measured Results](#measured-results) for why (insert throughput on a single local container, not query performance, is the actual bottleneck at 50M+; see [Design Decisions](#design-decisions--trade-offs) for the full story). The seeding, indexing, and aggregation approach is identical either way and scales linearly with document count; `scripts/seed_data.py --total 50000000` runs the same code path.

## Architecture

```
┌──────────────────────┐        HTTP (REST)        ┌───────────────────────┐
│  React Dashboard      │ ─────────────────────────▶│   FastAPI Backend      │
│  (Vite + Recharts)    │◀───────────────────────── │   (Motor / async)      │
└──────────┬────────────┘        JSON                └───────────┬───────────┘
           │                                                      │
           │ WebSocket (live event feed)                          │ aggregation pipelines
           ▼                                                      ▼
┌──────────────────────┐   broadcast on ingest        ┌───────────────────────┐
│  ConnectionManager     │◀──────────────────────────│      MongoDB 7.0        │
│  (broadcasts to all    │      (see note below)       │  events (time-series)  │
│   connected clients)   │                            │  ├─ TTL: 90 days       │
└────────────────────────┘                            │  ├─ (user_id, ts) idx  │
                                                        │  └─ (ts, event_type)  │
                                                        │  single-node replica  │
                                                        │  set (rs0)             │
                                                        └───────────────────────┘
```

> **Note on real-time updates**: the PRD's architecture calls for MongoDB change streams driving the live feed. We built that exact path (`db.watch()`, both collection- and database-level, with `showExpandedEvents`) and verified live against `mongo:7.0.43` that time-series collections do not reliably emit change-stream events for individual document inserts — confirmed both via the FastAPI app and directly in `mongosh` (see [Design Decisions](#design-decisions--trade-offs)). The live feed instead broadcasts over the same `ConnectionManager` directly from the `POST /api/v1/events` handler on successful insert, which is still genuinely real-time and driven by the same write path.

## Quickstart

```bash
docker compose up --build
```

| Service  | URL                          |
|----------|-------------------------------|
| Frontend | http://localhost:5260         |
| API      | http://localhost:8085         |
| API docs | http://localhost:8085/docs    |
| MongoDB  | mongodb://localhost:27050     |

Seed synthetic data (resumable, writes progress checkpoints, generated in chronological order — see [Design Decisions](#design-decisions--trade-offs)):

```bash
docker compose exec api python -m scripts.seed_data --total 5000000
```

Run the real before/after index benchmark against whatever is currently seeded:

```bash
docker compose exec api python -m scripts.benchmark
```

Results are written to `backend/benchmark_results.md` / `.json` — see [Measured Results](#measured-results) below for the numbers from this project's own run.

## Local Development

**Backend** (Python 3.11):

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env            # point MONGO_URI at a local mongod --replSet rs0
uvicorn app.main:app --reload
```

**Frontend**:

```bash
cd frontend
npm install
npm run dev
```

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/events` | Ingest a single event `{event_type, user_id, value, timestamp?}` |
| `GET` | `/api/v1/analytics/hourly?event_type=&hours=` | Hourly count/avg/min/max rollup |
| `GET` | `/api/v1/analytics/percentiles?event_type=` | p50/p75/p95/p99 of `value` via `$percentile` |
| `GET` | `/api/v1/analytics/cohort?days=` | `$facet` query: new users/day, per-user retention, engagement buckets |
| `WS` | `/api/v1/analytics/ws` | Live event stream, broadcast directly from the ingest handler on each insert (see note above) |
| `GET` | `/health` | Liveness check |

## Design Decisions & Trade-offs

- **Async Motor instead of the PRD's sync PyMongo.** The PRD's sample code uses blocking `pymongo.MongoClient` calls inside `async def` methods, which would block the FastAPI event loop under load — especially with a long-lived change-stream watcher running concurrently with request handling. We used the async Motor driver throughout instead.
- **`$percentile` operator instead of manual `$bucketAuto` + sort-in-Python.** The PRD's percentile pipeline buckets into 100 groups and interpolates client-side, which is imprecise and pulls all bucket boundaries into the app. MongoDB 7.0 added a native `$percentile` accumulator (`method: "approximate"`, backed by t-digest) that computes exact requested percentiles server-side in one pass. We used it and pinned the image to `mongo:7.0`.
- **Single-node replica set, not a sharded cluster.** The PRD's "10x faster queries" and "50M+ documents" targets don't require sharding to demonstrate — a single well-indexed node handles 50M documents comfortably. Change streams, however, *require* a replica set (even a one-member one) — standalone `mongod` cannot open them. We run a single-node `rs0` via a `mongo-init` one-shot container so change streams work without provisioning a multi-node cluster this project doesn't need.
- **Time-series collection's own TTL, not a manual TTL index.** MongoDB 5.0+ supports `expireAfterSeconds` directly on `db.createCollection(..., timeseries=...)`, which is what actually deletes whole time buckets efficiently. We used that instead of a separate manual TTL index on `timestamp` (which the PRD's sample code creates on a *non*-time-series collection).
- **Live updates broadcast directly on ingest, not via MongoDB change streams — a deviation discovered through real testing, not assumed upfront.** We implemented the PRD's change-stream design first: `db.events.watch()` at the collection level throws `MongoServerError: Cannot run aggregation on timeseries with namespace ...` because time-series collections are internally backed by a `system.buckets.*` view. The documented workaround is a database-level change stream filtered by `{"ns.coll": "events"}` — but live-testing that against a running `mongo:7.0.43` container (inserting documents while watching, both from the FastAPI app and directly in `mongosh`, with and without `showExpandedEvents: true`, waiting up to 40s) never produced a single change event for `events` inserts, while the identical watch on a plain non-time-series collection delivered events immediately. Time-series change-stream support is evidently still unreliable for per-document inserts in this version. We switched the live feed to broadcast over the WebSocket `ConnectionManager` directly from the `POST /api/v1/events` handler after a successful insert — still real-time, still driven by the actual write, just not via the change-stream mechanism the PRD specified.
- **Seed data is generated and inserted in chronological (hour-by-hour) order, not randomly-ordered timestamps — a fix driven by a real, measured performance collapse.** The first version of `scripts/seed_data.py` generated each document with a uniformly random timestamp across the whole 89-day window, matching how you'd naively simulate "historical" data. Running it live, insert throughput started at ~6,500 docs/sec and degraded steadily to under 1,000 docs/sec by ~5M documents. The cause: MongoDB time-series collections bucket writes by `(meta, time range)`, and an insert into a "hot" open bucket is cheap, but random timestamps scattered across 89 days force MongoDB to keep reopening buckets across the entire span instead of appending to one. Rewriting the generator to produce documents hour-by-hour, oldest-first — the way a real ingestion pipeline actually arrives — fixed it: throughput became stable at ~2,850 docs/sec with no degradation as the collection grew, confirmed by a live before/after test.
- **Scaled the seed target from the PRD's 50M+ down to 5M documents.** At the measured, stable ~2,850 docs/sec on a single local container, 50M documents would take roughly 5 hours to insert — a real, honest cost of bulk-writing into a time-series collection on modest local hardware, not a query-performance limitation (the aggregation pipelines themselves are fast; see below). 5M documents is enough to demonstrate and measure real indexing behavior at meaningful scale without the multi-hour local seed time. `scripts/seed_data.py` takes `--total` as a parameter and the exact same chronological-insert code path handles 50M+ if run for longer.
- **Secondary indexes as `meta.user_id` / `meta.event_type` (not top-level fields).** Time-series collections group most queryable dimensions under the `metaField` (`meta`); MongoDB indexes those sub-fields directly, which is what our compound indexes target.
- **Seeding is a one-shot script, not run automatically on every `docker compose up`.** 50M documents takes real minutes to insert; re-running it on every container start would make local iteration painful. It's resumable via a checkpoint document so a killed/restarted seed run picks up where it left off.
- **CI runs integration tests against a small dataset on a standalone (non-replica-set) `mongo:7.0` service container**, not the full 50M-document / replica-set stack — that keeps CI fast. Change-stream behavior is exercised live via `docker compose up`, not in CI, since GitHub-hosted service containers don't support the replica-set initiation step cleanly.

## Testing

```bash
cd backend
python -m pytest tests/unit          # pure pipeline-builder logic, no DB required
python -m pytest tests/integration   # real aggregation correctness against a live MongoDB
```

## Measured Results

Real wall-clock timings from `scripts/benchmark.py`, run against this project's own 5,000,000-document dataset (also in `backend/benchmark_results.md` / `.json`):

| Query | No secondary indexes | With secondary indexes | Speedup |
|---|---|---|---|
| Hourly rollup (`event_type` + time window) | 3.060s | 0.110s | **27.9x** |
| Percentiles (`$percentile` on `value`) | 1.830s | 1.655s | 1.1x |
| Cohort/retention/engagement (`$facet`) | 8.149s | 2.205s | **3.7x** |

The hourly and cohort queries see the PRD's claimed order-of-magnitude speedup because they filter on `meta.event_type` and/or `timestamp`, which the compound indexes directly serve. The percentile query barely benefits — it's honest, not fudged: it filters *only* on `meta.event_type` with no timestamp bound, so neither compound index (`(user_id, timestamp)` nor `(timestamp, event_type)`) narrows the scan much before the `$percentile` accumulator has to process the matched documents; the cost is dominated by that accumulation, not the initial filter.

## Tech Stack

- **Backend**: FastAPI, Motor (async MongoDB driver), Pydantic, Uvicorn
- **Database**: MongoDB 7.0 (time-series collections, `$facet`/`$percentile`/`$bucket` aggregations, single-node replica set)
- **Frontend**: React, TypeScript, Vite, Recharts
- **Infra**: Docker Compose, GitHub Actions CI
