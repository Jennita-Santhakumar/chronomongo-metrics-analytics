import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import get_db, init_db
from app.routes import analytics, events

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    await init_db(db)
    yield


app = FastAPI(title="MongoDB Time-Series Analytics Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(analytics.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
