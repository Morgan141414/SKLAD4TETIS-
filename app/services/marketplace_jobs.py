"""Small database jobs shared by HTTP lazy checks and the periodic runner."""
from typing import Any

BUY_REQUEST_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"open", "closed", "fulfilled"}),
    "closed": frozenset({"closed", "open", "fulfilled"}),
    "expired": frozenset({"expired", "open"}),
    "fulfilled": frozenset({"fulfilled"}),
}


def is_buy_request_status_transition_allowed(current: str, target: str) -> bool:
    return target in BUY_REQUEST_STATUS_TRANSITIONS.get(current, frozenset())


def expire_marketplace_buy_requests(connection: Any) -> int:
    """Expire due public requests and notify their owners exactly once.

    The status predicate makes the operation idempotent. The update and its
    notifications are one SQL statement, so a rollback cannot leave them out
    of sync. Callers must provide a transactional connection.
    """
    rows = connection.execute(
        """WITH expired AS (
               UPDATE marketplace_buy_requests
               SET status = 'expired', updated_at = NOW()
               WHERE status = 'open' AND expires_at <= NOW()
               RETURNING id, user_id, title
           )
           INSERT INTO marketplace_user_notifications
               (user_id, notification_type, title, body, entity_type, entity_id)
           SELECT user_id, 'buy_expired', 'Срок запроса истёк', LEFT(title, 500),
                  'buy_request', id
           FROM expired
           RETURNING id"""
    ).fetchall()
    return len(rows)
