"""Agent base: every agent runs audited registry tools, collects evidence, and uses the
LLM (mock by default) ONLY to narrate over the facts its tools returned."""
from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from app.llm.provider import FACTS_ONLY_SYSTEM_PROMPT, get_llm_provider
from app.metrics import observe_stage
from app.models import Evidence, Investigation
from app.tools.base import ToolContext, ToolRegistry, get_registry
from app.workflow.engine import record_stage


class BaseAgent:
    name = "base-agent"

    def __init__(self, session: Session, llm=None, approved: bool = False) -> None:
        self.session = session
        self.llm = llm or get_llm_provider()
        self.registry: ToolRegistry = get_registry()
        self.ctx = ToolContext(session=session, actor=self.name, approved=approved)

    # ---- tooling
    def use(self, tool_name: str, args: dict | None = None) -> dict:
        return self.registry.run(tool_name, args or {}, self.ctx)

    def narrate(self, prompt: str, facts: list[dict]) -> str:
        return self.llm.narrate(FACTS_ONLY_SYSTEM_PROMPT, prompt, facts)

    # ---- evidence
    def add_evidence(self, source: str, fact: str, reliability: str = "high",
                     raw_reference: str = "", application_id: str | None = None,
                     investigation_id: int | None = None) -> Evidence:
        row = Evidence(source=source, fact=fact, reliability=reliability,
                       raw_reference=raw_reference, application_id=application_id,
                       investigation_id=investigation_id)
        self.session.add(row)
        return row

    # ---- stage wrapper
    def stage(self, investigation: Investigation, stage: str,
              work: Callable[[], tuple[dict, dict, list[dict], str]]) -> dict:
        """work() returns (input_summary, output_summary, narration_facts, narration_prompt)."""
        started = time.perf_counter()
        try:
            input_summary, output_summary, facts, prompt = work()
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - recorded then re-raised
            duration_ms = int((time.perf_counter() - started) * 1000)
            observe_stage(self.name, stage, time.perf_counter() - started)
            record_stage(self.session, investigation, self.name, stage,
                         {"stage": stage}, {"error": str(exc)[:400]},
                         duration_ms=duration_ms, status="error")
            raise
        output_summary["narration"] = self.narrate(prompt, facts)
        duration_ms = int((time.perf_counter() - started) * 1000)
        observe_stage(self.name, stage, time.perf_counter() - started)
        record_stage(self.session, investigation, self.name, stage,
                     input_summary, output_summary, duration_ms=duration_ms)
        return output_summary
