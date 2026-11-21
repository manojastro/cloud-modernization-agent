"""Pytest bootstrap.

Environment variables MUST be configured before any ``app`` import, because
``app.config``/``app.db`` bind the SQLAlchemy engine at import time.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TMPDIR = Path(tempfile.mkdtemp(prefix="c15-tests-"))
os.environ["DATABASE_URL"] = "sqlite:///" + (_TMPDIR / "test.db").as_posix()
os.environ["LLM_MODE"] = "mock"
os.environ["ESTATE_SIZE"] = "48"
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture()
def fresh_db():
    """Drop and recreate every table so each test starts from an empty estate."""
    from app.db import reset_db

    reset_db()
    yield


@pytest.fixture()
def session(fresh_db):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
        s.rollback()
    finally:
        s.close()


@pytest.fixture()
def seeded(session):
    """A deterministic estate (size from ESTATE_SIZE env) committed and ready."""
    from simulator.loader import seed_estate

    counts = seed_estate(session)
    session.commit()
    return session


@pytest.fixture()
def planned(seeded):
    """Estate + full agent pipeline run (assessments, strategies, waves, risks)."""
    from app.pipeline import run_full_pipeline

    summary = run_full_pipeline(seeded)
    seeded.commit()
    return seeded, summary


@pytest.fixture(scope="session")
def api_client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def client(fresh_db, api_client):
    return api_client


@pytest.fixture()
def seeded_client(client):
    resp = client.post("/api/v1/simulator/seed", json={"size": 40})
    assert resp.status_code == 200, resp.text
    return client
