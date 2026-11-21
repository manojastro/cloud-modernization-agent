"""Strategy recommendation queries + the visible rules table."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import StrategyRecommendation
from app.schemas import StrategyOut, StrategyRuleOut
from app.strategy.rules_7r import RULES_TABLE_VISIBLE

router = APIRouter(prefix="/api/v1", tags=["strategy"])


@router.get("/strategy-rules", response_model=list[StrategyRuleOut])
def strategy_rules() -> list[StrategyRuleOut]:
    return [
        StrategyRuleOut(id=r["id"], name=r["name"], description=r["description"],
                        strategy=r["strategy"], order=i + 1)
        for i, r in enumerate(RULES_TABLE_VISIBLE)
    ]


@router.get("/strategies", response_model=list[StrategyOut])
def list_strategies(limit: int = Query(default=200, ge=1, le=400),
                    db: Session = Depends(get_db)) -> list[StrategyOut]:
    rows = db.query(StrategyRecommendation).order_by(
        StrategyRecommendation.application_id).limit(limit).all()
    return [_to_out(r) for r in rows]


@router.get("/strategies/{app_id}", response_model=StrategyOut)
def get_strategy(app_id: str, db: Session = Depends(get_db)) -> StrategyOut:
    r = (db.query(StrategyRecommendation)
         .filter(StrategyRecommendation.application_id == app_id).first())
    if r is None:
        raise HTTPException(status_code=404,
                            detail=f"no strategy classified for '{app_id}'")
    return _to_out(r)


def _to_out(r: StrategyRecommendation) -> StrategyOut:
    return StrategyOut(
        application_id=r.application_id, strategy=r.strategy,
        confidence=r.confidence, matched_rule_id=r.matched_rule_id,
        reasons=list(r.reasons or []), alternatives=list(r.alternatives or []),
        rule_trace=list(r.rule_trace or []), risk_level=r.risk_level,
        requires_approval=bool(r.requires_approval),
    )
