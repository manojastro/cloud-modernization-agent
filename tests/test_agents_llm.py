"""Agents + LLM layer: deterministic mock narration and hidden-dependency discovery."""
from simulator.generate_estate import HIDDEN_SOURCE, HIDDEN_TARGET
from app.agents.discovery import ApplicationDiscoveryAgent
from app.llm.provider import MockLLM, get_llm_provider
from app.models import Evidence, StageRun
from app.workflow.engine import start_investigation


def test_mock_llm_is_deterministic():
    llm = MockLLM()
    facts = [{"label": "runtime", "value": "python-flask"},
             {"label": "eol", "value": True}]
    a = llm.narrate("sys", "summarize", facts)
    b = llm.narrate("sys", "summarize", facts)
    assert a == b


def test_mock_llm_digest_changes_with_facts():
    llm = MockLLM()
    a = llm.narrate("sys", "p", [{"label": "x", "value": 1}])
    b = llm.narrate("sys", "p", [{"label": "x", "value": 2}])
    assert a != b


def test_mock_llm_narrates_only_facts_no_advice():
    llm = MockLLM()
    out = llm.narrate("sys", "decide the strategy",
                      [{"label": "usage", "value": 42}])
    # every content line maps to a supplied fact label; no recommendation verbs
    assert "[mock narration" in out
    assert "facts_considered=1 digest=" in out
    assert "- usage: 42" in out
    lowered = out.lower()
    assert "recommend" not in lowered and "i would" not in lowered


def test_get_llm_provider_defaults_to_mock():
    provider = get_llm_provider()
    assert provider.mode == "mock"


def test_discovery_agent_records_evidence_and_stage_runs(seeded):
    session = seeded
    inv = start_investigation(session, kind="migration", subject="estate")
    agent = ApplicationDiscoveryAgent(session)
    summary = agent.run(inv)
    session.commit()

    assert isinstance(summary, dict)
    stages = (session.query(StageRun)
              .filter(StageRun.investigation_id == inv.id).all())
    assert stages, "discovery must persist stage runs"
    assert all(s.status == "ok" for s in stages)

    evidence = session.query(Evidence).all()
    assert evidence, "undocumented dependencies must become evidence rows"
    hidden_evidence = [e for e in evidence
                       if HIDDEN_TARGET in e.fact or HIDDEN_SOURCE in e.fact]
    assert hidden_evidence, (
        "the agent must flag the hidden FTP dependency explicitly")
    for e in hidden_evidence:
        assert e.investigation_id == inv.id
        assert e.reliability in ("high", "medium", "low")
        assert e.raw_reference  # provenance pointer required
