from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.db import get_db
from app.schemas import EventIn
from app.ws_manager import manager

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post("", status_code=201)
async def create_event(event: EventIn, db=Depends(get_db)):
    timestamp = event.timestamp or datetime.now(timezone.utc)
    doc = {
        "timestamp": timestamp,
        "meta": {"event_type": event.event_type, "user_id": event.user_id},
        "value": event.value,
    }
    await db["events"].insert_one(doc)

    await manager.broadcast(
        {
            "event_type": event.event_type,
            "user_id": event.user_id,
            "value": event.value,
            "timestamp": timestamp.isoformat(),
        }
    )
    return {"status": "accepted"}
