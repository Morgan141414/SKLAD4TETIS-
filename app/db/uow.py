from __future__ import annotations

from types import TracebackType
from typing import Any

from app.db.session import get_session_factory


class UnitOfWork:
    def __init__(self, session_factory: Any | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()
        self.session: Any | None = None

    def __enter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
