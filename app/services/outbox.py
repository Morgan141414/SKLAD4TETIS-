"""Transactional outbox for reliable outbound notifications (email, webhook).

Business-mutating operations write a row into ``notification_outbox_events`` *in the same
transaction* as the domain change, then a background relay (`process_pending`)
delivers each event and marks it `delivered`. Failed deliveries are retried with
exponential backoff and eventually move to `failed`, so no notification is lost
on a service restart unlike the old fire-and-forget threads.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 30.0
DEFAULT_BATCH_SIZE = 50

EventPayload = dict[str, Any]
Handler = Callable[[EventPayload], None]


def enqueue(connection: Any, event_type: str, payload: EventPayload) -> int:
    """Record an outbox event inside the current transaction.

    The caller must be inside a ``database.transaction()`` block so the event is
    committed atomically with the business change.
    """
    from app.storage.sqlite import insert_and_get_id

    created_at = datetime.now(UTC).isoformat()
    return insert_and_get_id(
        connection,
        "INSERT INTO notification_outbox_events (event_type, payload, status, created_at)"
        " VALUES (?, ?, 'pending', ?)",
        (event_type, json.dumps(payload, ensure_ascii=False), created_at),
    )


def _next_attempt_at(attempts: int) -> str:
    delay = datetime.now(UTC) + timedelta(seconds=BACKOFF_BASE_SECONDS * (2 ** min(attempts, 6)))
    return delay.isoformat()


def process_pending(
    database: Any,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    handlers: dict[str, Handler] | None = None,
) -> dict[str, int]:
    """Deliver up to ``batch_size`` pending outbox events.

    Returns counts of delivered / failed events. Each event is handled in its own
    short transaction so a slow handler does not block the database for others.
    """
    if handlers is None:
        from app.services.outbox_handlers import HANDLERS

        handlers = HANDLERS

    now = datetime.now(UTC)
    connection = database.connect()
    try:
        rows = connection.execute(
            """SELECT id, event_type, payload, attempts
               FROM notification_outbox_events
               WHERE status = 'pending'
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY id
               LIMIT ?""",
            (now.isoformat(), batch_size),
        ).fetchall()
    finally:
        close_connection(database, connection)

    delivered = 0
    failed = 0
    delivered_events: list[dict[str, Any]] = []
    for row in rows:
        event_id = int(row["id"])
        event_type = str(row["event_type"])
        attempts = int(row["attempts"])
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}

        handler = handlers.get(event_type)
        try:
            if handler is not None:
                handler(payload)
            _mark_delivered(database, event_id)
            delivered += 1
            delivered_events.append({"type": event_type, "payload": payload})
        except Exception as error:  # noqa: BLE001 - retried by the relay
            logger.warning("Outbox event %s (%s) delivery failed: %s", event_id, event_type, error)
            _mark_failed(database, event_id, attempts + 1, str(error))
            failed += 1

    if delivered or failed:
        logger.info("Outbox relay delivered=%s failed=%s", delivered, failed)
    return {"delivered": delivered, "failed": failed, "events": delivered_events}


def _mark_delivered(database: Any, event_id: int) -> None:
    with database.transaction() as conn:
        conn.execute(
            """UPDATE notification_outbox_events
               SET status = 'delivered', delivered_at = ?
               WHERE id = ?""",
            (datetime.now(UTC).isoformat(), event_id),
        )


def _mark_failed(database: Any, event_id: int, attempts: int, error: str) -> None:
    status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
    with database.transaction() as conn:
        conn.execute(
            """UPDATE notification_outbox_events
               SET attempts = ?, last_error = ?, status = ?, next_attempt_at = ?
               WHERE id = ?""",
            (attempts, error[:2000], status, _next_attempt_at(attempts), event_id),
        )


def close_connection(database: Any, connection: Any) -> None:
    path = getattr(database, "path", None)
    if path != ":memory:":
        connection.close()