"""SQLite engine + session management.

The engine is created lazily so tests can repoint ``PORTMAN_HOME`` first. Call
``init_db()`` once at startup (or with an explicit URL in tests) to create the
schema.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _build(url: str | None) -> None:
    global _engine, _SessionLocal
    config.refresh_from_env()
    config.ensure_dirs()
    db_url = url or f"sqlite:///{config.DB_PATH}"
    _engine = create_engine(db_url, connect_args={"check_same_thread": False})
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine() -> Engine:
    if _engine is None:
        _build(None)
    assert _engine is not None
    return _engine


def init_db(url: str | None = None) -> Engine:
    """Create tables. Pass an explicit ``url`` (e.g. a temp file) in tests."""
    _build(url)
    assert _engine is not None
    Base.metadata.create_all(_engine)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commit on success, roll back on error."""
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
