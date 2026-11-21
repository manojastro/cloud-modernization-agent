"""SQLAlchemy engine/session wiring. SQLite default; PostgreSQL-compatible via DATABASE_URL."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_sqlite_url(url: str) -> str:
    """Anchor relative sqlite paths to the project root and create the parent dir."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    db_path = url[len(prefix):]
    if db_path in ("", ":memory:") or ":memory:" in db_path:
        return url
    path = Path(db_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "future": True}
    return {"pool_pre_ping": True, "future": True}


_settings = get_settings()
_database_url = _resolve_sqlite_url(
    os.environ.get("DATABASE_URL", _settings.database_url))

engine = create_engine(_database_url, **_engine_kwargs(_database_url))

if _database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db():
    """FastAPI dependency. Commits successful requests; rolls back failed ones."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope():
    """Context-managed session with commit/rollback for scripts and agents."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (create_all by design; see LIMITATIONS.md re: Alembic trim)."""
    from app.models import Base

    import app.models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    """Drop and recreate every table (simulator reset)."""
    from app.models import Base

    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
