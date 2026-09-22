# MongoDB Time-Series Analytics Platform

A high-scale event analytics system built on MongoDB's time-series collections: complex aggregation pipelines (hourly rollups, percentile distributions, cohort/retention analysis), TTL-based auto-expiration, compound secondary indexes, and a live-updating dashboard. Backend is FastAPI + Motor (async), frontend is React + Recharts.

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

Seed synthetic data (resumable, writes progress checkpoints):

```bash
docker compose exec api python -m scripts.seed_data --total 50000000
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
- **Secondary indexes as `meta.user_id` / `meta.event_type` (not top-level fields).** Time-series collections group most queryable dimensions under the `metaField` (`meta`); MongoDB indexes those sub-fields directly, which is what our compound indexes target.
- **Seeding is a one-shot script, not run automatically on every `docker compose up`.** 50M documents takes real minutes to insert; re-running it on every container start would make local iteration painful. It's resumable via a checkpoint document so a killed/restarted seed run picks up where it left off.
- **CI runs integration tests against a small dataset on a standalone (non-replica-set) `mongo:7.0` service container**, not the full 50M-document / replica-set stack — that keeps CI fast. Change-stream behavior is exercised live via `docker compose up`, not in CI, since GitHub-hosted service containers don't support the replica-set initiation step cleanly.

## Testing

```bash
cd backend
pytest tests/unit          # pure pipeline-builder logic, no DB required
pytest tests/integration   # real aggregation correctness against a live MongoDB
```

## Measured Results

See `backend/benchmark_results.md` for the full table generated by `scripts/benchmark.py` against this project's own seeded dataset — real wall-clock timings comparing the aggregation queries with and without the compound secondary indexes, not fabricated numbers.

## Tech Stack

- **Backend**: FastAPI, Motor (async MongoDB driver), Pydantic, Uvicorn
- **Database**: MongoDB 7.0 (time-series collections, `$facet`/`$percentile`/`$bucket` aggregations, single-node replica set)
- **Frontend**: React, TypeScript, Vite, Recharts
- **Infra**: Docker Compose, GitHub Actions CI
