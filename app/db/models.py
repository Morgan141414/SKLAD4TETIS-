from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.db.base import Base

try:
    from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, Text
    from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
    from sqlalchemy.orm import Mapped, mapped_column
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal local envs
    BigInteger = Boolean = DateTime = Integer = Numeric = Text = None  # type: ignore[assignment]
    INET = JSONB = UUID = None  # type: ignore[assignment]
    Mapped = Any  # type: ignore[assignment]
    mapped_column = None  # type: ignore[assignment]


if Base.metadata is not None and mapped_column is not None:

    class StockBalance(Base):
        __tablename__ = "stock_balances"

        batch_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        warehouse_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
        reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)


    class StockDocument(Base):
        __tablename__ = "stock_documents"

        id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        document_type: Mapped[str] = mapped_column(Text, nullable=False)
        status: Mapped[str] = mapped_column(Text, nullable=False)
        warehouse_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
        supplier_id: Mapped[int | None] = mapped_column(BigInteger)
        created_by: Mapped[str] = mapped_column(Text, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


    class AuditLog(Base):
        __tablename__ = "audit_log"

        id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        actor_id: Mapped[str] = mapped_column(Text, nullable=False)
        action: Mapped[str] = mapped_column(Text, nullable=False)
        entity_type: Mapped[str] = mapped_column(Text, nullable=False)
        entity_id: Mapped[str] = mapped_column(Text, nullable=False)
        warehouse_id: Mapped[int | None] = mapped_column(BigInteger)
        payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
        request_id: Mapped[str | None] = mapped_column(Text)
        correlation_id: Mapped[str | None] = mapped_column(Text)
        ip_address: Mapped[str | None] = mapped_column(INET)
        user_agent: Mapped[str | None] = mapped_column(Text)
        previous_hash: Mapped[str | None] = mapped_column(Text)
        record_hash: Mapped[str | None] = mapped_column(Text)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


    class IdempotencyKey(Base):
        __tablename__ = "idempotency_keys"

        id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        key: Mapped[str] = mapped_column(Text, nullable=False)
        actor_id: Mapped[str] = mapped_column(Text, nullable=False)
        method: Mapped[str] = mapped_column(Text, nullable=False)
        path: Mapped[str] = mapped_column(Text, nullable=False)
        request_hash: Mapped[str] = mapped_column(Text, nullable=False)
        status: Mapped[str] = mapped_column(Text, nullable=False)
        response_status: Mapped[int | None] = mapped_column(Integer)
        response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
        resource_type: Mapped[str | None] = mapped_column(Text)
        resource_id: Mapped[str | None] = mapped_column(Text)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
        expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


    class OutboxEvent(Base):
        __tablename__ = "outbox_events"

        id: Mapped[str] = mapped_column(UUID, primary_key=True)
        event_type: Mapped[str] = mapped_column(Text, nullable=False)
        aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
        aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
        warehouse_id: Mapped[int | None] = mapped_column(BigInteger)
        payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
        status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
        attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        last_error: Mapped[str | None] = mapped_column(Text)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
        published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
