"""Prometheus instrumentation (module-level so re-created apps in tests don't double-register)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

TOOL_DURATION = Histogram(
    "cma_tool_duration_seconds", "Tool execution duration", ["tool", "risk_level"]
)
STAGE_DURATION = Histogram(
    "cma_agent_stage_duration_seconds", "Agent stage duration", ["agent", "stage"]
)
LLM_LATENCY = Histogram(
    "cma_llm_latency_seconds", "LLM (mock or live) completion latency", ["provider"]
)
TOOL_ERRORS = Counter(
    "cma_tool_errors_total", "Tool execution errors/refusals", ["tool", "kind"]
)
WAVE_APPS_MIGRATED = Counter(
    "cma_wave_apps_migrated_total", "Apps migrated per outcome", ["wave", "outcome"]
)


def observe_stage(agent: str, stage: str, duration_s: float) -> None:
    STAGE_DURATION.labels(agent=agent, stage=stage).observe(duration_s)


def observe_tool(tool: str, risk_level: str, duration_s: float) -> None:
    TOOL_DURATION.labels(tool=tool, risk_level=risk_level).observe(duration_s)


def observe_llm(provider: str, latency_s: float) -> None:
    LLM_LATENCY.labels(provider=provider).observe(latency_s)


def count_tool_error(tool: str, kind: str) -> None:
    TOOL_ERRORS.labels(tool=tool, kind=kind).inc()


def count_migration(wave: int | str, outcome: str) -> None:
    WAVE_APPS_MIGRATED.labels(wave=str(wave), outcome=outcome).inc()
