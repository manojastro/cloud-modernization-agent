"""Tool infrastructure: specs, an allow-list registry, argument validation, risk gating
and full audit persistence. No shell/subprocess tools exist anywhere in this project."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.metrics import count_tool_error, observe_tool
from app.models import ToolCall


class ToolError(RuntimeError):
    pass


class ToolRefused(ToolError):
    """Raised when a tool call is denied (unknown tool, missing approval, bad args)."""


@dataclass
class ToolContext:
    session: Session
    actor: str = "system"
    approved: bool = False  # True only after a persisted human approval


@dataclass
class ToolSpec:
    name: str
    purpose: str
    input_schema: dict[str, str]          # arg -> type name
    required_args: list[str] = field(default_factory=list)
    permission: str = "estate:read"
    risk_level: str = "LOW"               # LOW | MEDIUM | HIGH
    timeout_seconds: int = 30
    handler: Callable[[dict, ToolContext], dict] | None = None

    @property
    def output_schema(self) -> dict:
        return {"type": "object", "description": f"result of {self.name}"}


_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float),
    "boolean": (bool,), "null": (type(None),),
}


def _validate_args(spec: ToolSpec, args: dict) -> None:
    if not isinstance(args, dict):
        raise ToolRefused(f"arguments for '{spec.name}' must be an object")
    missing = [k for k in spec.required_args if k not in args]
    if missing:
        raise ToolRefused(f"missing required arguments for '{spec.name}': {missing}")
    for key, value in args.items():
        expected = spec.input_schema.get(key)
        if expected is None:
            continue  # tolerate extra keys; handlers are narrow
        allowed = _TYPE_CHECKS.get(expected)
        if allowed and not isinstance(value, allowed) or (
            expected == "integer" and isinstance(value, bool)
        ):
            raise ToolRefused(
                f"argument '{key}' for '{spec.name}' must be {expected}, "
                f"got {type(value).__name__}")


def _summarize(result: Any, limit: int = 400) -> str:
    try:
        text = json.dumps(result, default=str)[:limit]
    except Exception:  # noqa: BLE001
        text = str(result)[:limit]
    return text


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool '{spec.name}' already registered")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def specs(self) -> list[dict]:
        return [
            {
                "name": s.name, "purpose": s.purpose, "input_schema": s.input_schema,
                "required": s.required_args, "permission": s.permission,
                "risk_level": s.risk_level, "timeout_seconds": s.timeout_seconds,
                "output_schema": s.output_schema,
            }
            for s in sorted(self._tools.values(), key=lambda t: t.name)
        ]

    def run(self, name: str, args: dict | None, ctx: ToolContext) -> dict:
        args = args or {}
        started = time.perf_counter()

        def audit(allowed: bool, result_summary: str, error: str | None = None,
                  risk_level: str = "LOW") -> None:
            session: Session = ctx.session
            session.add(ToolCall(
                tool_name=name, arguments=_safe_args(args), caller=ctx.actor,
                risk_level=risk_level, allowed=allowed,
                duration_ms=int((time.perf_counter() - started) * 1000),
                result_summary=result_summary[:900], error=error[:900] if error else None,
            ))

        spec = self._tools.get(name)
        if spec is None:
            count_tool_error(name, "unknown_tool")
            audit(False, "", f"unknown tool '{name}'", risk_level="LOW")
            raise ToolRefused(f"unknown tool '{name}'")

        try:
            _validate_args(spec, args)
        except ToolRefused as exc:
            count_tool_error(name, "invalid_arguments")
            audit(False, "", str(exc), risk_level=spec.risk_level)
            raise

        if spec.risk_level == "HIGH" and not ctx.approved:
            count_tool_error(name, "approval_required")
            audit(False, "", "refused: high-risk tool requires persisted approval context",
                  risk_level=spec.risk_level)
            raise ToolRefused(
                f"tool '{name}' is high-risk and requires an approved decision "
                "(human approval gate)")

        try:
            result = spec.handler(args, ctx)
        except Exception as exc:  # noqa: BLE001 - audited then re-raised as ToolError
            count_tool_error(name, "handler_error")
            audit(True, "", f"{type(exc).__name__}: {exc}", risk_level=spec.risk_level)
            if isinstance(exc, ToolError):
                raise
            raise ToolError(f"tool '{name}' failed: {exc}") from exc

        observe_tool(name, spec.risk_level, time.perf_counter() - started)
        audit(True, _summarize(result))
        return result


def _safe_args(args: dict) -> dict:
    """Never persist secret-looking values into the audit trail."""
    clean = {}
    for key, value in args.items():
        lowered = key.lower()
        if any(token in lowered for token in ("secret", "token", "api_key", "password")):
            clean[key] = "***redacted***"
        else:
            clean[key] = value
    return clean


_REGISTRY: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        from app.tools.estate_tools import build_default_registry

        _REGISTRY = build_default_registry()
    return _REGISTRY
