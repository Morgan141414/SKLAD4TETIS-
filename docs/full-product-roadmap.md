# Full Product Roadmap

Цель: довести сервис склада до полноценного production-продукта по ТЗ, а не оставить MVP.

## Текущее состояние

Уже реализовано backend-ядро:

- справочники товаров, категорий, поставщиков и складов;
- партионный учет, карантин/блокировка партии;
- остатки: общий, резерв, свободный;
- приход, списание, FEFO-списание;
- документы прихода/списания с проведением;
- перемещения между складами/кабинетами;
- возвраты из отделения и поставщику;
- резервы и автоматическое истечение резервов;
- инвентаризация с блокировкой склада;
- уведомления по низкому остатку;
- audit log;
- WebSocket-каркас событий;
- 27 тестов бизнес-инвариантов.

## Критичные минусы

1. SQLite вместо PostgreSQL.
   Это главный технический риск: нет row-level locking, нормальных миграций, production-конкурентности и надежного append-only аудита.

2. Один крупный `WarehouseService`.
   Логика уже достаточно большая. Дальше ее нужно разделить на доменные сервисы, иначе продукт станет дорогим в сопровождении.

3. Нет полноценного RBAC.
   В медицинском контексте нельзя ограничиваться `X-Actor-Id`. Нужны роли, права и область доступа по складам/отделениям.

4. Audit log не защищен на уровне БД.
   Сейчас он append-only на уровне приложения. Для production нужны ограничения/триггеры/политики.

5. Realtime пока локальный.
   WebSocket-каркас есть, но для нескольких процессов нужен Redis Pub/Sub или Streams.

6. Нет фоновых worker-задач.
   Нужны периодические задачи: резервы, сроки годности, reorder, ABC/XYZ, карантинные просрочки, ретраи интеграций.

7. Нет frontend/PWA.
   По ТЗ нужен рабочий интерфейс: desktop, admin panel и планшетный PWA.

## Целевой backend

Модульный монолит на FastAPI:

```text
app/
  api/
  core/
  db/
  models/
  schemas/
  repositories/
  services/
    stock.py
    documents.py
    inventory.py
    reservations.py
    returns.py
    quarantine.py
    audit.py
    notifications.py
    analytics.py
    rbac.py
  integrations/
    accounting.py
    edo.py
    keycloak.py
    object_storage.py
    mqtt.py
  realtime/
  tasks/
```

## Приоритет 1: Production foundation

- PostgreSQL 15+.
- SQLAlchemy 2.x.
- Alembic migrations.
- Docker Compose: API, PostgreSQL, Redis, worker.
- Перенос SQLite-схемы в миграции.
- Транзакции с `SELECT ... FOR UPDATE` для остатков.
- Idempotency key для проведения документов и внешних запросов.
- Health/readiness endpoints.

## Приоритет 2: Security and RBAC

- Keycloak/OAuth2 JWT verification.
- Локальные роли и permissions.
- Scope доступа:
  - `all`;
  - `assigned_warehouses`;
  - `own_department`;
  - `category_limited`.
- Проверка scope в каждом query, а не только в UI.
- Audit запрещенных попыток доступа.

## Приоритет 3: Documents and approval workflow

- Все движения через документы:
  - приход;
  - списание;
  - перемещение;
  - возврат;
  - инвентаризация;
  - карантинное решение.
- Статусы:
  - draft;
  - submitted;
  - approved;
  - posted;
  - cancelled.
- Идемпотентное проведение.
- Печатные формы и PDF.

## Приоритет 4: Notifications and workers

- Worker-процесс.
- Periodic jobs:
  - low stock;
  - expiry reminders;
  - reservation expiration;
  - quarantine overdue;
  - monthly ABC/XYZ;
  - reorder draft generation.
- In-app notifications.
- WebSocket broadcast через Redis.

## Приоритет 5: Full ТЗ modules

- Карантинная зона с workflow.
- Контролируемые вещества/ПКУ.
- Barcode/price tags.
- Packing/repacking.
- ABC/XYZ analysis.
- Reorder point and purchase request drafts.
- Supplier map and logistics tracking.
- Supplier ratings and moderation.
- EDO and accounting integration.
- IoT temperature sensors via MQTT.
- Auctions.
- AI purchase-risk assistant.

## Приоритет 6: Frontend

- Desktop web app.
- Admin panel.
- Tablet PWA.
- Offline sync for PWA.
- Russian UI first, i18n-ready for Kazakh.

## Definition of Done

Фича считается готовой только если:

- есть миграция БД;
- есть сервисные тесты;
- есть API-тесты для критичных сценариев;
- есть audit log для write-операций;
- есть RBAC/scope проверки;
- есть OpenAPI schema;
- есть обработка ошибок;
- есть документация;
- нет отрицательных остатков и частичных транзакций;
- серверная копия обновлена и тесты проходят на сервере.

