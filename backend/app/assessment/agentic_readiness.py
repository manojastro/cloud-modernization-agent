"""Agentic readiness assessment (the differentiator): a deterministic 9-point checklist
scoring how safely an AI agent could operate this application's interface."""
from __future__ import annotations

from dataclasses import dataclass

ITEMS: list[tuple[str, str]] = [
    ("documented_api", "Documented API contract"),
    ("authentication", "Authentication on the interface"),
    ("least_privilege_feasible", "Least-privilege credentials feasible"),
    ("idempotent_operations", "Idempotent operations"),
    ("auditability", "Audit trail / observability"),
    ("rate_limit_support", "Rate limiting supported"),
    ("tool_friendly_interface", "Tool-friendly machine interface"),
    ("structured_errors", "Structured error responses"),
    ("safe_retries", "Safe retry semantics"),
]

MODERN_API = {"REST-internal", "REST-public", "gRPC"}


@dataclass
class AgenticResult:
    items: list[dict]
    score: int
    band: str


def _band(score: int) -> str:
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def evaluate_agentic_readiness(app) -> AgenticResult:
    """app: Application ORM instance (with runtime_details loaded)."""
    d = app.runtime_details
    api = app.api_surface
    auth = app.auth_method
    runtime_eol = bool(d and d.runtime_eol)

    idempotent = api in MODERN_API and app.statefulness == "stateless"
    structured_errors = not runtime_eol

    checks = {
        "documented_api": (
            api in MODERN_API,
            f"api_surface={api}; "
            + ("machine-readable contract assumed for REST/gRPC surfaces" if api in MODERN_API else "no documented contract"),
        ),
        "authentication": (
            auth in ("sso", "ldap", "local-db"),
            f"auth_method={auth}" + ("" if auth in ("sso", "ldap", "local-db") else "; weak or absent auth blocks agent access"),
        ),
        "least_privilege_feasible": (
            not (d and d.hardcoded_secrets_found) and auth != "none",
            "scoped credentials plausible"
            if (not (d and d.hardcoded_secrets_found) and auth != "none")
            else "hardcoded secrets / no auth prevent scoped credential issuance",
        ),
        "idempotent_operations": (
            idempotent,
            "stateless request/response surface supports retries-with-same-effect"
            if idempotent else "stateful or non-API surface makes idempotency unverifiable",
        ),
        "auditability": (
            bool(d and d.has_observability),
            "monitoring integration present" if (d and d.has_observability) else "no observability: agent actions would be unauditable",
        ),
        "rate_limit_support": (
            api in ("REST-public", "gRPC"),
            "edge gateway/rate limiter expected on public or RPC surface"
            if api in ("REST-public", "gRPC") else "no gateway-managed surface for throttling",
        ),
        "tool_friendly_interface": (
            api in MODERN_API,
            "JSON-over-HTTP/RPC suits tool invocation" if api in MODERN_API else "interface not suited to direct tool use",
        ),
        "structured_errors": (
            structured_errors,
            "modern runtime: structured error responses feasible"
            if structured_errors else "EOL runtime: error formats legacy/unparsed",
        ),
        "safe_retries": (
            idempotent and structured_errors,
            "idempotency + structured errors enable bounded retries"
            if (idempotent and structured_errors)
            else "retries risk duplicate side effects or unparseable failures",
        ),
    }

    labels = dict(ITEMS)
    items = []
    score = 0
    for key, label in ITEMS:
        passed, note = checks[key]
        score += 1 if passed else 0
        items.append({"item_key": key, "label": label, "passed": passed, "note": note})

    return AgenticResult(items=items, score=score, band=_band(score))
