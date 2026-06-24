from __future__ import annotations

try:
    from sqlalchemy.orm import DeclarativeBase
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal local envs
    DeclarativeBase = None  # type: ignore[assignment]


if DeclarativeBase is not None:

    class Base(DeclarativeBase):
        pass

else:

    class Base:  # type: ignore[no-redef]
        metadata = None
