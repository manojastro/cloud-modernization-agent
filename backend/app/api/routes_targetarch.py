"""Target architecture endpoints (structured spec + optional YAML render)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TargetArchitecture
from app.schemas import TargetArchitectureOut
from app.targetarch.generator import generate_for_app, render_yaml

router = APIRouter(prefix="/api/v1", tags=["target-architecture"])


@router.get("/target-architectures", response_model=list[dict])
def list_target_architectures(db: Session = Depends(get_db)) -> list[dict]:
    rows = (db.query(TargetArchitecture)
            .order_by(TargetArchitecture.application_id).all())
    seen: set[tuple[str, str]] = set()
    out = []
    for r in rows:
        key = (r.application_id, r.provider_profile)
        if key in seen:
            continue
        seen.add(key)
        out.append({"application_id": r.application_id,
                    "provider_profile": r.provider_profile,
                    "cost_delta_monthly": r.cost_delta_monthly})
    return out


@router.get("/target-architecture/{app_id}", response_model=TargetArchitectureOut)
def get_target_architecture(
    app_id: str,
    provider: str = Query(default="aws", pattern="^(aws|azure|gcp)$"),
    format: str = Query(default="json", pattern="^(json|yaml)$"),
    db: Session = Depends(get_db),
):
    try:
        row = generate_for_app(db, app_id, provider)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if format == "yaml":
        return {"application_id": row.application_id,
                "provider_profile": row.provider_profile,
                "spec": {},
                "cost_delta_monthly": row.cost_delta_monthly,
                "yaml": render_yaml(row.spec)}
    return TargetArchitectureOut(application_id=row.application_id,
                                 provider_profile=row.provider_profile,
                                 spec=row.spec,
                                 cost_delta_monthly=row.cost_delta_monthly)
