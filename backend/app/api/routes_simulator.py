"""Estate simulator endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import SeedRequest, SeedResponse
from simulator.loader import seed_estate

router = APIRouter(prefix="/api/v1/simulator", tags=["simulator"])


@router.post("/seed", response_model=SeedResponse)
def seed(payload: SeedRequest | None = None, db: Session = Depends(get_db)) -> SeedResponse:
    payload = payload or SeedRequest()
    counts = seed_estate(db, size=payload.size, reset=payload.reset)
    return SeedResponse(**counts)
