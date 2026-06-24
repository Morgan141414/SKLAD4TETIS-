from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import get_settings

try:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal local envs
    create_engine = None  # type: ignore[assignment]
    Engine = object  # type: ignore[assignment,misc]
    Session = object  # type: ignore[assignment,misc]
    sessionmaker = None  # type: ignore[assignment]


_engine: Engine | None = None
_session_factory = None


def get_engine() -> Engine:
    if create_engine is None:
        raise RuntimeError("SQLAlchemy is required for the PostgreSQL runtime")

    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory():
    if sessionmaker is None:
        raise RuntimeError("SQLAlchemy is required for the PostgreSQL runtime")

    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
