from datetime import date

from pydantic import BaseModel, Field


class EntryCreate(BaseModel):
    date: date
    distance_km: float = Field(ge=0)
    duration_min: float = Field(ge=0)
    notes: str = ""


class EntryOut(EntryCreate):
    id: int


class LoginRequest(BaseModel):
    username: str
    password: str
