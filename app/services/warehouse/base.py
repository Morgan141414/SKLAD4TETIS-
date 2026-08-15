from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.storage.base import WarehouseDatabase
from app.services.outbox import enqueue

PRODUCT_UNITS = (

    "шт",
    "уп",
    "рулон",
    "флакон",
    "бут",
    "бутылка",
    "пакет",
    "таблетка",
    "капсула",
    "ампула",
    "мл",
    "л",
    "г",
    "кг",
    "м",
    "см",
    "набор",
    "пара",
)



class WarehouseServiceBase:
    def __init__(self, database: WarehouseDatabase) -> None:
        self.database = database

    def _close_connection(self, connection: Any) -> None:
        if getattr(self.database, "path", None) != ":memory:":
            connection.close()

    def _is_postgresql(self, connection: Any) -> bool:
        return getattr(connection, "dialect", None) == "postgresql"

    def _date_from_db(self, value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    def _datetime_from_db(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    def _enqueue_outbox(self, connection: Any, event_type: str, payload: dict[str, Any]) -> int:
        """Record an outbox event in the current transaction (atomic with the change)."""
        return enqueue(connection, event_type, payload)
