# Production Migration Plan

Этот план переводит текущий backend из SQLite-прототипа в production-ready основу без потери уже покрытых бизнес-инвариантов.

## Принцип

Текущие 27+ тестов считаются acceptance contract. Любая миграция архитектуры обязана сохранить эти сценарии:

- нельзя списать/переместить/вернуть больше свободного остатка;
- резервы уменьшают свободный остаток;
- FEFO списывает ближайшие сроки годности первыми;
- документы не меняют остаток до проведения;
- проведение документов идемпотентно;
- инвентаризация блокирует обычные движения;
- возвраты и перемещения атомарны;
- audit log пишется для write-операций.

## Шаг 1: ActorContext and RBAC foundation

Статус: начато.

- Ввести `ActorContext`.
- Описать роли ТЗ:
  - зав. склада;
  - старшая медсестра;
  - медсестра;
  - врач;
  - прочие пользователи.
- Описать permissions.
- Описать warehouse scope.
- На первом этапе не ломать текущий `X-Actor-Id`, но заменить его внутренне на dev actor.

## Шаг 2: API tests

- Добавить FastAPI TestClient smoke tests для ключевых endpoints.
- Зафиксировать response contracts.
- Добавить единый формат ошибок.
- Добавить пагинацию для списков.

## Шаг 3: Unit of Work boundary

- Ввести абстракцию транзакции.
- Вынести audit writer.
- Вынести event recorder.
- Оставить SQLite adapter как временную реализацию.

## Шаг 4: Split services

Разделить текущий `WarehouseService`:

- `CatalogService`;
- `StockService`;
- `StockDocumentService`;
- `TransferService`;
- `ReturnService`;
- `ReservationService`;
- `InventoryService`;
- `NotificationService`;
- `AuditService`.

На время миграции можно оставить `WarehouseService` как фасад, чтобы не переписывать все routes сразу.

## Шаг 5: SQLAlchemy models

Статус: начат foundation. Добавлены `app/db/base.py`, `app/db/session.py`, `app/db/uow.py` и первые SQLAlchemy-модели для runtime-critical таблиц в `app/db/models.py`.

- Расширить SQLAlchemy models до полного соответствия `0001_initial_postgresql.sql`.
- Типы:
  - `NUMERIC(18, 3)` для количеств;
  - `NUMERIC(18, 2)` или `NUMERIC(18, 4)` для цен;
  - `TIMESTAMP WITH TIME ZONE` для дат/времени;
  - `JSONB` для payload;
  - `TEXT` + check constraints для статусов на первом этапе.

## Шаг 6: Alembic migration

Статус: добавлены `alembic.ini`, `app/db/migrations/env.py`, шаблон миграции и baseline migration `0001_initial_postgresql`, которая исполняет проверенный SQL scaffold.

- Проверить миграцию на пустой PostgreSQL.
- Добавить CI smoke test для `alembic upgrade head`.
- После появления полного набора SQLAlchemy models включить autogenerate drift-check.

## Шаг 7: Row locks

Все операции, меняющие остатки, должны блокировать строки `stock_balances`:

```sql
SELECT * FROM stock_balances
WHERE batch_id = :batch_id AND warehouse_id = :warehouse_id
FOR UPDATE;
```

Инвентаризация должна блокировать склад или отдельную lock-таблицу.

## Шаг 8: Idempotency

Добавить `idempotency_keys`:

- key;
- actor_id;
- method;
- path;
- request_hash;
- status (`processing`, `succeeded`, `failed`);
- response_status;
- response_body;
- resource_type;
- resource_id;
- locked_at;
- created_at;
- expires_at.

Повтор того же ключа с тем же body возвращает сохраненный response. Тот же ключ с другим body дает `409`.

## Шаг 9: Outbox events

Добавить `outbox_events`:

- event_id;
- event_type;
- aggregate_type;
- aggregate_id;
- warehouse_id;
- payload;
- status;
- attempts;
- created_at;
- published_at.

Сервис пишет событие в outbox в той же транзакции, где меняет остаток.

## Шаг 10: Redis/NATS realtime

- Worker читает outbox.
- Публикует событие в Redis Pub/Sub, Redis Streams или NATS.
- WebSocket manager читает брокер.
- Клиенты получают только события разрешенных складов.

## Шаг 11: Background jobs

Перенести ручные jobs из API в worker:

- expiration of reservations;
- low-stock notifications;
- expiry reminders;
- quarantine overdue;
- ABC/XYZ monthly;
- reorder draft generation;
- accounting sync retries.

## Шаг 12: Production security

- Keycloak/OAuth2.
- JWT validation.
- RBAC dependency.
- Request ID middleware.
- Audit forbidden attempts.
- CORS policy.
- Secrets через env/secret store.

## Шаг 13: Observability and operations

- Structured JSON logs.
- Prometheus metrics.
- Health/readiness.
- Backup/restore procedure.
- CI/CD pipeline.
- Migration test in pipeline.
- Smoke test after deploy.
