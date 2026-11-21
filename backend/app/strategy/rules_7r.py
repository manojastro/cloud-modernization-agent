"""Deterministic 7R strategy classification.

An ordered, VISIBLE rules table decides every strategy. Each rule predicate receives a
plain fact dict and returns matched signals; the LLM never chooses strategies. First
match wins; later matching rules become documented alternatives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

STRATEGIES = ["REHOST", "REPLATFORM", "REFACTOR", "REPURCHASE", "RETAIN", "RETIRE", "RELOCATE"]

RISK_BY_STRATEGY = {
    "REHOST": "low", "REPLATFORM": "medium", "REFACTOR": "high",
    "REPURCHASE": "medium", "RETAIN": "low", "RETIRE": "medium", "RELOCATE": "medium",
}
APPROVAL_BY_STRATEGY = {"RETIRE": True, "REFACTOR": True}


@dataclass
class RuleMatch:
    rule_id: str
    strategy: str
    signals: int
    reasons: list[str] = field(default_factory=list)
    decisive_bonus: float = 0.0


@dataclass
class StrategyResult:
    strategy: str
    confidence: float
    matched_rule_id: str
    reasons: list[str]
    alternatives: list[str]
    rule_trace: list[dict]
    risk_level: str
    requires_approval: bool


class Rule:
    def __init__(self, rule_id: str, name: str, description: str, strategy: str,
                 predicate: Callable[[dict], RuleMatch | None]) -> None:
        self.id = rule_id
        self.name = name
        self.description = description
        self.strategy = strategy
        self.predicate = predicate


def _r01_retire(ctx: dict) -> RuleMatch | None:
    if (ctx["usage_per_day"] <= 30 and ctx["criticality"] <= 2
            and ctx["monthly_usage_trend_pct"] <= -50):
        return RuleMatch(
            "R01-retire-candidate", "RETIRE",
            signals=3,
            reasons=[
                f"usage {ctx['usage_per_day']}/day is near zero",
                f"criticality {ctx['criticality']}/5 is minimal",
                f"usage trend {ctx['monthly_usage_trend_pct']}%/yr is in steep decline",
            ],
            decisive_bonus=0.10,
        )
    return None


def _r02_repurchase(ctx: dict) -> RuleMatch | None:
    if ctx["commodity_capability"]:
        return RuleMatch(
            "R02-repurchase-commodity", "REPURCHASE",
            signals=1,
            reasons=[
                "homegrown implementation of a commodity capability "
                "(file hub / basic CMS class); SaaS-equivalents exist",
            ],
            decisive_bonus=0.18,
        )
    return None


def _r03_retain_mainframe(ctx: dict) -> RuleMatch | None:
    if ctx["runtime_id"] == "cobol-mainframe" and ctx["change_frequency"] == "rare":
        alt = ("RELOCATE via automated conversion"
               if ctx["criticality"] < 4 else None)
        m = RuleMatch(
            "R03-retain-mainframe-stable", "RETAIN",
            signals=2,
            reasons=[
                "mainframe-simulated batch workload",
                f"change frequency '{ctx['change_frequency']}' with last change "
                f"{ctx['last_change_months_ago']} months ago: business value exceeds migration cost",
            ],
            decisive_bonus=0.14,
        )
        if alt:
            m.reasons.append(alt + " noted as alternative only")
        return m
    return None


def _r04_refactor_monolith(ctx: dict) -> RuleMatch | None:
    if ctx["monolith_loc"] >= 300_000 and ctx["debt_index"] >= 60 and ctx["criticality"] >= 4:
        return RuleMatch(
            "R04-refactor-monolith", "REFACTOR",
            signals=3,
            reasons=[
                f"monolith of {ctx['monolith_loc']:,} LOC blocks incremental delivery",
                f"technical debt index {ctx['debt_index']:.0f}/100 is high",
                f"criticality {ctx['criticality']}/5 justifies phased investment",
            ],
            decisive_bonus=0.06,
        )
    return None


def _r05_relocate_vm(ctx: dict) -> RuleMatch | None:
    if ctx["specialized_os_deps"] and ctx["hypervisor_hosted"] and not ctx["runtime_eol"]:
        return RuleMatch(
            "R05-relocate-lift-vm", "RELOCATE",
            signals=2,
            reasons=[
                "runtime is supported but workload carries specialized OS/licence coupling "
                "(per-socket licensing, NUMA tuning)",
                "hypervisor-hosted: lift as VM images to cloud IaaS without code change",
            ],
            decisive_bonus=0.08,
        )
    return None


def _r06_replatform_runtime(ctx: dict) -> RuleMatch | None:
    if ctx["runtime_eol"] and ctx["managed_db_path"] and ctx["runtime_id"] != "cobol-mainframe":
        return RuleMatch(
            "R06-replatform-managed-runtime", "REPLATFORM",
            signals=2,
            reasons=[
                "runtime is EOL; containerize onto a supported managed runtime",
                f"database has a managed target path ('{ctx['db_compatibility']}')",
            ],
            decisive_bonus=0.04,
        )
    return None


def _r07_rehost_container(ctx: dict) -> RuleMatch | None:
    if (not ctx["runtime_eol"] and ctx["statefulness"] == "stateless"
            and ctx["debt_index"] < 40 and ctx["monolith_loc"] < 200_000):
        return RuleMatch(
            "R07-rehost-container", "REHOST",
            signals=3,
            reasons=[
                "supported runtime, no forced change",
                "stateless: safe to containerize without redesign",
                f"low debt index ({ctx['debt_index']:.0f}/100) and moderate codebase size",
            ],
            decisive_bonus=0.02,
        )
    return None


def _r08_default_replatform(ctx: dict) -> RuleMatch | None:
    if ctx["runtime_eol"] or ctx["os_eol"] or ctx["db_compatibility"] in ("conversion-required", "none"):
        bits = []
        if ctx["runtime_eol"]:
            bits.append("EOL runtime")
        if ctx["os_eol"]:
            bits.append("EOL OS")
        if ctx["db_compatibility"] in ("conversion-required", "none"):
            bits.append(f"database compatibility '{ctx['db_compatibility']}'")
        return RuleMatch(
            "R08-default-eol-replatform", "REPLATFORM",
            signals=len(bits),
            reasons=["default EOL posture: replatform to remove platform risk (" + "; ".join(bits) + ")"],
        )
    return None


def _r09_default_rehost(ctx: dict) -> RuleMatch | None:
    return RuleMatch(
        "R09-default-rehost", "REHOST",
        signals=1,
        reasons=["no blocking findings: rehost into containers at current behaviour"],
    )


RULES_TABLE: list[Rule] = [
    Rule("R01-retire-candidate", "Retire near-zero-value apps", "Near-zero usage + low criticality + steep decline", "RETIRE", _r01_retire),
    Rule("R02-repurchase-commodity", "Buy commodity capability", "Homegrown commodity capability (FTP hub, basic CMS)", "REPURCHASE", _r02_repurchase),
    Rule("R03-retain-mainframe-stable", "Retain stable mainframe batch", "Mainframe-sim batch + rare change", "RETAIN", _r03_retain_mainframe),
    Rule("R04-refactor-monolith", "Refactor high-debt monoliths", "Monolith >=300k LOC + debt >=60 + criticality >=4", "REFACTOR", _r04_refactor_monolith),
    Rule("R05-relocate-lift-vm", "Relocate licence-coupled VMs", "Specialized OS/licence deps + hypervisor-hosted + modern runtime", "RELOCATE", _r05_relocate_vm),
    Rule("R06-replatform-managed-runtime", "Replatform off EOL runtimes", "EOL runtime + managed DB path exists + not mainframe", "REPLATFORM", _r06_replatform_runtime),
    Rule("R07-rehost-container", "Rehost clean stateless apps", "Healthy runtime + stateless + low debt + small codebase", "REHOST", _r07_rehost_container),
    Rule("R08-default-eol-replatform", "Default: EOL anything -> replatform", "Any EOL signal not caught above", "REPLATFORM", _r08_default_replatform),
    Rule("R09-default-rehost", "Default: otherwise rehost", "Catch-all for healthy unclassified apps", "REHOST", _r09_default_rehost),
]


def build_context(app, d, db_meta) -> dict:
    """Fact dict from ORM objects (Application, AppRuntimeDetails, DatabaseRegistry)."""
    return {
        "application_id": app.id,
        "usage_per_day": app.usage_per_day,
        "criticality": app.criticality,
        "monthly_usage_trend_pct": app.monthly_usage_trend_pct,
        "commodity_capability": bool(app.commodity_capability),
        "runtime_id": app.runtime_id,
        "os_id": app.os_id,
        "change_frequency": d.change_frequency if d else "monthly",
        "last_change_months_ago": d.last_change_months_ago if d else 12,
        "monolith_loc": d.monolith_loc if d else 0,
        "debt_index": 0.0,  # injected by caller after debt computation
        "specialized_os_deps": bool(app.specialized_os_deps),
        "hypervisor_hosted": bool(app.hypervisor_hosted),
        "runtime_eol": bool(d.runtime_eol) if d else False,
        "os_eol": bool(d.os_eol) if d else False,
        "db_compatibility": db_meta.compatibility if db_meta else "direct",
        "managed_db_path": bool(db_meta and db_meta.managed_equivalent
                                and db_meta.compatibility != "none"),
        "statefulness": app.statefulness,
        "compliance_scope": app.compliance_scope,
    }


def classify(fact_ctx: dict) -> StrategyResult:
    trace: list[dict] = []
    matches: list[RuleMatch] = []
    for idx, rule in enumerate(RULES_TABLE):
        match = rule.predicate(fact_ctx)
        trace.append({
            "order": idx + 1, "rule_id": rule.id, "strategy": match.strategy if match else None,
            "matched": match is not None, "description": rule.description,
        })
        if match:
            matches.append(match)

    if not matches:  # defensive; R09 always matches
        raise RuntimeError("rules table produced no match")

    chosen = matches[0]
    confidence = min(0.97, 0.50 + 0.06 * chosen.signals + chosen.decisive_bonus)
    alternatives = [m.strategy for m in matches[1:4]]
    # dedupe preserving order
    seen: set[str] = set()
    alternatives = [a for a in alternatives if not (a in seen or seen.add(a))]

    return StrategyResult(
        strategy=chosen.strategy,
        confidence=round(confidence, 2),
        matched_rule_id=chosen.rule_id,
        reasons=chosen.reasons,
        alternatives=alternatives,
        rule_trace=trace,
        risk_level=RISK_BY_STRATEGY[chosen.strategy],
        requires_approval=APPROVAL_BY_STRATEGY.get(chosen.strategy, False),
    )


RULES_TABLE_VISIBLE = [
    {"id": r.id, "name": r.name, "description": r.description, "strategy": r.strategy}
    for r in RULES_TABLE
]
