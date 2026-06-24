from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.errors import ValidationError
from app.storage.sqlite import SQLiteDatabase, now_iso

try:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal local envs
    text = None  # type: ignore[assignment]

    class SQLAlchemyIntegrityError(Exception):  # type: ignore[no-redef]
        pass


class DuplicateIdempotencyKeyError(Exception):
    pass


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    actor_id: str
    method: str
    path: str
    request_hash: str
    status: str
    response_status: int | None = None
    response_body: Any | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    created_at: str | None = None
    locked_at: str | None = None
    expires_at: str | None = None


class IdempotencyRepository(Protocol):
    def create_processing(
        self,
        *,
        key: str,
        actor_id: str,
        method: str,
        path: str,
        request_hash: str,
        locked_at: str,
    ) -> None:
        ...

    def get(self, *, key: str, actor_id: str) -> IdempotencyRecord | None:
        ...

    def refresh_processing_lock(self, *, key: str, actor_id: str, locked_at: str) -> bool:
        ...

    def mark_succeeded(
        self,
        *,
        key: str,
        actor_id: str,
        response_status: int,
        response_body: Any,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> IdempotencyRecord:
        ...

    def mark_failed(self, *, key: str, actor_id: str) -> None:
        ...


class SQLiteIdempotencyRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_processing(
        self,
        *,
        key: str,
        actor_id: str,
        method: str,
        path: str,
        request_hash: str,
        locked_at: str,
    ) -> None:
        with self.database.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO idempotency_keys(
                      key, actor_id, method, path, request_hash, status, created_at, locked_at
                    ) VALUES (?, ?, ?, ?, ?, 'processing', ?, ?)
                    """,
                    (key, actor_id, method, path, request_hash, now_iso(), locked_at),
                )
            except sqlite3.IntegrityError as error:
                raise DuplicateIdempotencyKeyError from error

    def get(self, *, key: str, actor_id: str) -> IdempotencyRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM idempotency_keys
                WHERE actor_id = ? AND key = ?
                """,
                (actor_id, key),
            ).fetchone()
            return self._record(row) if row is not None else None

    def refresh_processing_lock(self, *, key: str, actor_id: str, locked_at: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE idempotency_keys
                SET locked_at = ?
                WHERE actor_id = ? AND key = ? AND status = 'processing'
                """,
                (locked_at, actor_id, key),
            )
            return cursor.rowcount == 1

    def mark_succeeded(
        self,
        *,
        key: str,
        actor_id: str,
        response_status: int,
        response_body: Any,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> IdempotencyRecord:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM idempotency_keys
                WHERE actor_id = ? AND key = ?
                """,
                (actor_id, key),
            ).fetchone()
            if row is None:
                raise ValidationError("Idempotency key was not claimed")
            connection.execute(
                """
                UPDATE idempotency_keys
                SET status = 'succeeded',
                    response_status = ?,
                    response_body = ?,
                    resource_type = ?,
                    resource_id = ?
                WHERE actor_id = ? AND key = ?
                """,
                (
                    response_status,
                    json.dumps(response_body, default=str),
                    resource_type,
                    resource_id,
                    actor_id,
                    key,
                ),
            )
            return IdempotencyRecord(
                key=key,
                actor_id=actor_id,
                method=row["method"],
                path=row["path"],
                request_hash=row["request_hash"],
                status="succeeded",
                response_status=response_status,
                response_body=response_body,
                resource_type=resource_type,
                resource_id=resource_id,
                created_at=row["created_at"],
                locked_at=row["locked_at"],
                expires_at=row["expires_at"],
            )

    def mark_failed(self, *, key: str, actor_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE idempotency_keys
                SET status = 'failed'
                WHERE actor_id = ? AND key = ? AND status = 'processing'
                """,
                (actor_id, key),
            )

    def _record(self, row: Any) -> IdempotencyRecord:
        response_body = json.loads(row["response_body"]) if row["response_body"] else None
        return IdempotencyRecord(
            key=row["key"],
            actor_id=row["actor_id"],
            method=row["method"],
            path=row["path"],
            request_hash=row["request_hash"],
            status=row["status"],
            response_status=row["response_status"],
            response_body=response_body,
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            created_at=row["created_at"],
            locked_at=row["locked_at"],
            expires_at=row["expires_at"],
        )


class PostgresIdempotencyRepository:
    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        if text is None:
            raise RuntimeError("SQLAlchemy is required for the PostgreSQL idempotency repository")
        if session_factory is None:
            from app.db.session import get_session_factory

            session_factory = get_session_factory()
        self.session_factory = session_factory

    @contextmanager
    def _session(self) -> Iterator[Any]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_processing(
        self,
        *,
        key: str,
        actor_id: str,
        method: str,
        path: str,
        request_hash: str,
        locked_at: str,
    ) -> None:
        with self._session() as session:
            try:
                session.execute(
                    text(
                        """
                        INSERT INTO idempotency_keys(
                          key, actor_id, method, path, request_hash, status, created_at, locked_at
                        ) VALUES (
                          :key, :actor_id, :method, :path, :request_hash, 'processing',
                          CAST(:created_at AS timestamptz), CAST(:locked_at AS timestamptz)
                        )
                        """
                    ),
                    {
                        "key": key,
                        "actor_id": actor_id,
                        "method": method,
                        "path": path,
                        "request_hash": request_hash,
                        "created_at": now_iso(),
                        "locked_at": locked_at,
                    },
                )
            except SQLAlchemyIntegrityError as error:
                raise DuplicateIdempotencyKeyError from error

    def get(self, *, key: str, actor_id: str) -> IdempotencyRecord | None:
        with self._session() as session:
            row = session.execute(
                text(
                    """
                    SELECT * FROM idempotency_keys
                    WHERE actor_id = :actor_id AND key = :key
                    """
                ),
                {"actor_id": actor_id, "key": key},
            ).mappings().first()
            return self._record(row) if row is not None else None

    def refresh_processing_lock(self, *, key: str, actor_id: str, locked_at: str) -> bool:
        with self._session() as session:
            result = session.execute(
                text(
                    """
                    UPDATE idempotency_keys
                    SET locked_at = CAST(:locked_at AS timestamptz)
                    WHERE actor_id = :actor_id AND key = :key AND status = 'processing'
                    """
                ),
                {"locked_at": locked_at, "actor_id": actor_id, "key": key},
            )
            return result.rowcount == 1

    def mark_succeeded(
        self,
        *,
        key: str,
        actor_id: str,
        response_status: int,
        response_body: Any,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> IdempotencyRecord:
        with self._session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT * FROM idempotency_keys
                    WHERE actor_id = :actor_id AND key = :key
                    """
                ),
                {"actor_id": actor_id, "key": key},
            ).mappings().first()
            if existing is None:
                raise ValidationError("Idempotency key was not claimed")

            row = session.execute(
                text(
                    """
                    UPDATE idempotency_keys
                    SET status = 'succeeded',
                        response_status = :response_status,
                        response_body = CAST(:response_body AS jsonb),
                        resource_type = :resource_type,
                        resource_id = :resource_id
                    WHERE actor_id = :actor_id AND key = :key
                    RETURNING *
                    """
                ),
                {
                    "response_status": response_status,
                    "response_body": json.dumps(response_body, default=str),
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "actor_id": actor_id,
                    "key": key,
                },
            ).mappings().one()
            return self._record(row)

    def mark_failed(self, *, key: str, actor_id: str) -> None:
        with self._session() as session:
            session.execute(
                text(
                    """
                    UPDATE idempotency_keys
                    SET status = 'failed'
                    WHERE actor_id = :actor_id AND key = :key AND status = 'processing'
                    """
                ),
                {"actor_id": actor_id, "key": key},
            )

    def _record(self, row: Any) -> IdempotencyRecord:
        response_body = row["response_body"]
        if isinstance(response_body, str):
            response_body = json.loads(response_body)
        return IdempotencyRecord(
            key=row["key"],
            actor_id=row["actor_id"],
            method=row["method"],
            path=row["path"],
            request_hash=row["request_hash"],
            status=row["status"],
            response_status=row["response_status"],
            response_body=response_body,
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            created_at=row["created_at"],
            locked_at=row["locked_at"],
            expires_at=row["expires_at"],
        )
