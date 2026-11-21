"""LLM provider layer.

Design rule for this project: deterministic engines COMPUTE, the LLM (mock or live)
only ARTICULATES reasoning over facts that were handed to it. The MockLLM is fully
deterministic and never invents facts; the OpenAICompatibleProvider sends the same
facts-only prompt contract to any OpenAI-compatible endpoint.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.metrics import observe_llm


class LLMProviderError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    mode: str

    def narrate(self, system: str, prompt: str, facts: list[dict[str, Any]]) -> str: ...


def _facts_digest(facts: list[dict[str, Any]]) -> str:
    payload = json.dumps(facts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class MockLLM:
    """Deterministic facts-only narrator. mode='mock'. Same inputs -> same output."""

    name = "mock"
    mode = "mock"

    def narrate(self, system: str, prompt: str, facts: list[dict[str, Any]]) -> str:
        started = time.perf_counter()
        lines = [
            f"[mock narration | system={system}]",
            f"facts_considered={len(facts)} digest={_facts_digest(facts)}",
        ]
        for fact in facts[:8]:
            label = fact.get("label") or fact.get("fact") or str(fact)
            value = fact.get("value", "")
            lines.append(f"- {label}: {value}".replace("\n", " "))
        if len(facts) > 8:
            lines.append(f"- ...and {len(facts) - 8} more facts (truncated)")
        observe_llm(self.name, max(time.perf_counter() - started, 0.0001))
        return "\n".join(lines)


class OpenAICompatibleProvider:
    """Any OpenAI-compatible /chat/completions endpoint (vLLM, Ollama, LM Studio...)."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.name = "openai-compatible"
        self.mode = "openai-compatible"
        self._settings = settings
        self._client = client or httpx.Client(timeout=30.0)

    def narrate(self, system: str, prompt: str, facts: list[dict[str, Any]]) -> str:
        started = time.perf_counter()
        fact_block = "\n".join(
            f"- {f.get('label', 'fact')}: {f.get('value', '')}" for f in facts
        )
        user_content = (
            "You are narrating a migration analysis. Use ONLY the facts below. "
            "Do not add numbers, products, or claims that are not in the facts.\n\n"
            f"TASK:\n{prompt}\n\nFACTS:\n{fact_block}\n"
        )
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"
        payload = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        }
        try:
            resp = self._client.post(
                self._settings.llm_base_url.rstrip("/") + "/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - surfaced to caller as provider error
            raise LLMProviderError(f"openai-compatible call failed: {exc}") from exc
        finally:
            observe_llm(self.name, max(time.perf_counter() - started, 0.0001))
        return text


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings_cached()
    if settings.is_mock:
        return MockLLM()
    return OpenAICompatibleProvider(settings)


def get_settings_cached():  # local import to avoid cycles in tests that reset cache
    from app.config import get_settings

    return get_settings()


FACTS_ONLY_SYSTEM_PROMPT = (
    "You are the narration voice of a cloud migration analysis system. "
    "Deterministic engines compute every number and classification. "
    "Your only job is to explain the supplied facts clearly. Never introduce new facts."
)
