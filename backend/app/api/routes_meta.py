"""Meta/health/readiness/metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Application
from app.schemas import HealthResponse, MetaResponse, ReadinessResponse

router = APIRouter()


def _seeded(db: Session) -> bool:
    return db.query(Application.id).first() is not None


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="ok")


@router.get("/readiness", response_model=ReadinessResponse)
def readiness(db: Session = Depends(get_db)) -> ReadinessResponse:
    checks = {"database": False, "estate_seeded": _seeded(db)}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # noqa: BLE001
        checks["database"] = False
    return ReadinessResponse(ready=all(checks.values()), checks=checks)


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/meta", response_model=MetaResponse)
def meta(db: Session = Depends(get_db)) -> MetaResponse:
    settings = get_settings()
    seeded = _seeded(db)
    return MetaResponse(
        name=settings.app_name,
        version=settings.version,
        llm_mode=settings.llm_mode,
        mock_mode=settings.is_mock,
        badge="MOCK MODE" if settings.is_mock else None,
        estate_seeded=seeded,
        application_count=db.query(Application).count(),
        default_provider_profile=settings.default_provider_profile,
    )
