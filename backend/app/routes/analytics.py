from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.aggregations import AnalyticsService
from app.db import get_db
from app.ws_manager import manager

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def get_service(db=Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(db)


@router.get("/hourly")
async def hourly(event_type: str, hours: int = 24, service: AnalyticsService = Depends(get_service)):
    return await service.get_hourly_stats(event_type, hours)


@router.get("/percentiles")
async def percentiles(event_type: str, service: AnalyticsService = Depends(get_service)):
    return await service.get_percentiles(event_type)


@router.get("/cohort")
async def cohort(days: int = 30, service: AnalyticsService = Depends(get_service)):
    return await service.get_cohort_analysis(days)


@router.websocket("/ws")
async def ws_events(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
