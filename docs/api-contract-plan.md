# API Contract Plan

Цель: привести API к production contract без резкой поломки текущих клиентов.

## Разрывы

- Основные routes получили `response_model`; остаются secondary/admin/integration endpoints по мере появления.
- Ошибки возвращают `detail: str`, а нужен стабильный envelope.
- RBAC подключен к основным routes через `ActorContext` headers только при явном `SKLAD_DEV_AUTH_ENABLED=true`; без этого API возвращает `401` вместо dev manager. Объектные stock/reservation/inventory routes проверяют warehouse scope после загрузки сущности по id. Массовое истечение резервов, notifications и audit-log требуют warehouse filter для scoped actors. Batch status update проверяет доступ ко всем складам, где лежит партия, и поддерживает idempotency. Audit-log хранит `warehouse_id` и редактирует чувствительные поля в read response. WebSocket balances проверяет STOCK_READ и фильтрует доставку по warehouse scope. Следующий шаг - Keycloak/JWT и scope для background flows.
- Списки получили единый pagination envelope `items/total/limit/offset`.
- Idempotency headers подключены к критичным mutating endpoints; остаются менее опасные catalog/admin/update flows.
- Transitional header auth допустим только для local/demo при `SKLAD_DEV_AUTH_ENABLED=true`; production должен перевести HTTP и WebSocket на один JWT verifier.

## Первый порядок исправлений

1. Подключить Keycloak/JWT verification вместо header-only actor context.
2. Усилить service/query scope проверки для realtime, background jobs и будущих read endpoints.
3. Добавить response models для будущих secondary/admin/integration endpoints.
4. Перевести realtime events на outbox после PostgreSQL Unit of Work.
5. Добавить TestClient integration tests, когда dev-зависимости стабилизируются.

## Правила

- Все новые mutating endpoints должны иметь response model.
- Ошибки должны возвращать:

```json
{
  "code": "not_found",
  "message": "Entity not found",
  "details": {}
}
```

- Posting/stock/reservation/inventory mutating endpoints должны иметь `Idempotency-Key`.
- Replay не должен повторно выполнять service operation и не должен повторно публиковать realtime event.
- Списки должны иметь `limit` + `offset` или cursor и единый envelope.
- RBAC должен проверяться и на route boundary, и в service/query scope.
- Header-only RBAC допустим только как explicit transitional dev mode через `SKLAD_DEV_AUTH_ENABLED=true`; production должен проверять JWT issuer/audience/expiry/roles.

## Тестирование в текущем окружении

Пока локально не гарантированы FastAPI/httpx/pytest, поэтому contract checks можно начинать через `unittest` + `ast`:

- route has `response_model`;
- route has idempotency dependency/header;
- object-id routes enforce warehouse scope from loaded entity;
- list endpoint has pagination parameters;
- error envelope function returns machine-readable code.

Когда dev-зависимости стабилизируются, добавить TestClient integration tests.
