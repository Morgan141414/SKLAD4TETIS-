from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.errors import IdempotencyConflictError
from app.repositories.idempotency import (
    DuplicateIdempotencyKeyError,
    IdempotencyRecord,
    IdempotencyRepository,
    SQLiteIdempotencyRepository,
)
from app.storage.sqlite import SQLiteDatabase, now_iso


@dataclass(frozen=True)
class IdempotencyClaim:
    key: str
    actor_id: str
    status: str
    created: bool
    replayed: bool
    response_status: int | None = None
    response_body: Any | None = None
    resource_type: str | None = None
    resource_id: str | None = None


class IdempotencyStore:
    def __init__(self, repository: IdempotencyRepository | SQLiteDatabase) -> None:
        if isinstance(repository, SQLiteDatabase):
            repository = SQLiteIdempotencyRepository(repository)
        self.repository = repository

    def claim(
        self,
        *,
        key: str,
        actor_id: str,
        method: str,
        path: str,
        request_hash: str,
        processing_timeout_seconds: int = 300,
    ) -> IdempotencyClaim:
        locked_at = now_iso()
        try:
            self.repository.create_processing(
                key=key,
                actor_id=actor_id,
                method=method,
                path=path,
                request_hash=request_hash,
                locked_at=locked_at,
            )
            return IdempotencyClaim(
                key=key,
                actor_id=actor_id,
                status="processing",
                created=True,
                replayed=False,
            )
        except DuplicateIdempotencyKeyError:
            record = self.repository.get(key=key, actor_id=actor_id)
            if record is None:
                raise

        self._validate_same_request(record, method=method, path=path, request_hash=request_hash)

        if record.status == "processing":
            if self._is_processing_stale(record.locked_at, processing_timeout_seconds):
                if self.repository.refresh_processing_lock(
                    key=key,
                    actor_id=actor_id,
                    locked_at=locked_at,
                ):
                    return IdempotencyClaim(
                        key=key,
                        actor_id=actor_id,
                        status="processing",
                        created=True,
                        replayed=False,
                    )
            raise IdempotencyConflictError("Idempotency key is already processing")

        if record.status == "failed":
            raise IdempotencyConflictError("Previous request with this idempotency key failed")

        return self._claim_from_record(record, created=False)

    def succeed(
        self,
        *,
        key: str,
        actor_id: str,
        response_status: int,
        response_body: Any,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> IdempotencyClaim:
        record = self.repository.mark_succeeded(
            key=key,
            actor_id=actor_id,
            response_status=response_status,
            response_body=response_body,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        return self._claim_from_record(record, created=False)

    def fail(self, *, key: str, actor_id: str) -> None:
        self.repository.mark_failed(key=key, actor_id=actor_id)

    def _claim_from_record(self, record: IdempotencyRecord, *, created: bool) -> IdempotencyClaim:
        return IdempotencyClaim(
            key=record.key,
            actor_id=record.actor_id,
            status=record.status,
            created=created,
            replayed=record.status == "succeeded" and not created,
            response_status=record.response_status,
            response_body=record.response_body,
            resource_type=record.resource_type,
            resource_id=record.resource_id,
        )

    def _validate_same_request(
        self,
        record: IdempotencyRecord,
        *,
        method: str,
        path: str,
        request_hash: str,
    ) -> None:
        if record.method != method or record.path != path:
            raise IdempotencyConflictError(
                "Idempotency key was already used for a different endpoint"
            )
        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request body"
            )

    def _is_processing_stale(
        self,
        locked_at: str | datetime | None,
        processing_timeout_seconds: int,
    ) -> bool:
        if locked_at is None:
            return True
        locked_at_datetime = locked_at
        if isinstance(locked_at, str):
            locked_at_datetime = datetime.fromisoformat(locked_at)
        if locked_at_datetime.tzinfo is None:
            locked_at_datetime = locked_at_datetime.replace(tzinfo=UTC)
        elapsed = datetime.now(UTC) - locked_at_datetime.astimezone(UTC)
        return elapsed.total_seconds() > processing_timeout_seconds


def _jsonable(data: Any) -> Any:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    if hasattr(data, "dict"):
        return data.dict()
    return data


def request_hash(data: Any) -> str:
    body = json.dumps(_jsonable(data), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def run_idempotent(
    *,
    idempotency_key: str | None,
    store: IdempotencyStore,
    actor_id: str,
    method: str,
    path: str,
    payload: Any,
    response_status: int,
    resource_type: str,
    operation: Callable[[], Any],
) -> tuple[Any, bool]:
    if idempotency_key is None:
        return operation(), False

    claim = store.claim(
        key=idempotency_key,
        actor_id=actor_id,
        method=method,
        path=path,
        request_hash=request_hash(payload),
    )
    if claim.replayed:
        return claim.response_body or {}, True

    try:
        response = operation()
    except Exception:
        store.fail(key=idempotency_key, actor_id=actor_id)
        raise

    store.succeed(
        key=idempotency_key,
        actor_id=actor_id,
        response_status=response_status,
        response_body=response,
        resource_type=resource_type,
        resource_id=str(response.get("id", "")) if isinstance(response, dict) else None,
    )
    return response, False
