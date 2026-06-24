# PostgreSQL Migration Runbook

Этот порядок нужен для безопасной репетиции и последующего cutover с SQLite на PostgreSQL. Production нельзя переключать только фактом наличия adapter-а: сначала должны пройти backup, preflight, загрузка, reconciliation и smoke-тесты.

## Preconditions

- Текущий SQLite файл найден и доступен только на чтение для проверки.
- Есть окно обслуживания, где можно остановить записи в SKLAD.
- PostgreSQL база создана пустой, права пользователя проверены.
- Alembic baseline применен:

```bash
SKLAD_DATABASE_BACKEND=postgresql \
SKLAD_DATABASE_URL="$POSTGRES_URL" \
alembic upgrade head
```

## 1. Freeze Writes

- Остановить API или перевести систему в maintenance-режим.
- Отключить background jobs на время переноса.
- Убедиться, что никто не создает приход, списание, перемещение, резерв или инвентаризацию.

## 2. Backup

SQLite snapshot:

```bash
mkdir -p backups
sqlite3 /opt/sklad/sklad.db ".backup 'backups/sklad-cutover-$(date +%Y%m%d-%H%M%S).db'"
```

Файлы проекта:

```bash
tar --exclude=.git --exclude=.venv --exclude=sklad.db \
  -czf "backups/sklad-files-$(date +%Y%m%d-%H%M%S).tar.gz" /opt/sklad
```

## 3. SQLite Preflight

```bash
scripts/sklad_sqlite_preflight.py backups/sklad-cutover-YYYYMMDD-HHMMSS.db --json \
  > backups/sklad-preflight-YYYYMMDD-HHMMSS.json
```

Нельзя продолжать, если `ok=false`. Сначала исправить:

- `PRAGMA integrity_check`;
- `foreign_key_check`;
- invalid decimals/json;
- отрицательные остатки;
- `reserved_quantity > quantity`;
- duplicate unread notifications или duplicate draft purchase requests.

## 4. Load To PostgreSQL

Для rehearsal можно использовать `--truncate` на отдельной staging-базе:

```bash
scripts/sklad_sqlite_to_postgres.py \
  backups/sklad-cutover-YYYYMMDD-HHMMSS.db \
  "$POSTGRES_URL" \
  --truncate \
  > backups/sklad-load-YYYYMMDD-HHMMSS.json
```

Скрипт сохраняет исходные `id`, конвертирует decimal/date/timestamp/boolean/jsonb и обновляет PostgreSQL sequences через `setval()`.

## 5. Reconcile

```bash
scripts/sklad_postgres_reconcile.py \
  backups/sklad-cutover-YYYYMMDD-HHMMSS.db \
  "$POSTGRES_URL" \
  --json \
  > backups/sklad-reconcile-YYYYMMDD-HHMMSS.json
```

Нельзя переключать runtime, если `ok=false`.

Минимально должны совпасть:

- количество строк во всех runtime-таблицах;
- диапазоны `id`;
- counts по статусам и типам;
- агрегаты остатков по склад+товар;
- агрегаты движений по тип+склад.

## 6. Runtime Smoke

На staging окружении запустить API с:

```bash
SKLAD_DATABASE_BACKEND=postgresql
SKLAD_DATABASE_URL="$POSTGRES_URL"
SKLAD_DEV_AUTH_ENABLED=false
```

Для технической проверки runtime-слоя запустить mutating smoke на отдельной staging-базе:

```bash
scripts/sklad_postgres_runtime_smoke.py \
  http://127.0.0.1:8121/api/v1 \
  --json \
  > backups/sklad-runtime-smoke-YYYYMMDD-HHMMSS.json
```

Скрипт `scripts/sklad_postgres_runtime_smoke.py` создает отдельные тестовые справочники, приход, резерв/use, документ перемещения/post, списание, уведомления и заявку на закупку. Нельзя запускать его на production-базе после cutover без отдельного разрешения, потому что smoke намеренно пишет данные.

Проверить:

- `/api/v1/health`;
- `/api/v1/health/ready`;
- вход через Tetis/production Bearer JWT;
- список складов, товаров, партий и остатков;
- карточку партии;
- приход, списание FEFO, резерв/use/release;
- перемещение между складами;
- инвентаризацию;
- уведомления и заявки на закупку;
- audit log и CSV exports.

## 7. Cutover Decision

Переключение разрешено только если:

- preflight `ok=true`;
- load завершился без ошибок;
- reconcile `ok=true`;
- smoke прошел;
- есть SQLite backup и PostgreSQL `pg_dump`;
- есть команда rollback и ответственный за решение.

## Rollback

До новых PostgreSQL writes:

```bash
systemctl stop sklad
# вернуть SKLAD_DATABASE_BACKEND=sqlite и SQLite snapshot
systemctl start sklad
```

После новых PostgreSQL writes автоматического безопасного отката в SQLite нет. Перед rollback нужно принять бизнес-решение: потерять post-cutover изменения или делать ручной reverse export. PostgreSQL перед откатом сохранить:

```bash
pg_dump "$POSTGRES_URL" --format=custom --file "backups/sklad-failed-cutover-$(date +%Y%m%d-%H%M%S).dump"
```
