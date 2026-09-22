from datetime import datetime

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_type: str
    user_id: str
    value: float
    timestamp: datetime | None = None


class EventOut(BaseModel):
    event_type: str
    user_id: str
    value: float
    timestamp: datetime


class HourlyStat(BaseModel):
    id: str = Field(alias="_id")
    count: int
    avg_value: float
    max_value: float
    min_value: float

    model_config = {"populate_by_name": True}
