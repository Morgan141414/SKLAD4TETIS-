# Deployment Checklist

Этот чеклист нужен перед передачей проекта на тестовый или production-like сервер.

## Перед запуском

- Проверить `.env`: `SKLAD_DEV_AUTH_ENABLED=false` для всех не-demo окружений.
- Задать `SKLAD_JWT_HMAC_SECRET` или подключить целевой OIDC/Keycloak слой в следующем production-инкременте.
- Для demo можно использовать SQLite. Для production PostgreSQL использовать только после `docs/postgresql-migration-runbook.md`: backup, preflight, load, reconciliation и smoke.
- Проверить, что `SKLAD_BACKGROUND_JOBS_ENABLED` включен только там, где нужен автоматический выпуск просроченных резервов и уведомления.

## Запуск

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8120
```

Проверки после запуска:

```bash
curl -sS http://127.0.0.1:8120/api/v1/health
curl -sS http://127.0.0.1:8120/api/v1/health/ready
```

## Smoke test

- Открыть `/app/`.
- Создать категорию, поставщика, склад и товар.
- Принять товар.
- Открыть карточку партии из таблицы остатков.
- Провести перемещение или списание.
- Проверить движение в **История склада**.
- Создать и провести инвентаризацию на тестовом складе.
- Выгрузить CSV на экранах остатков, движений и аналитики.

## Backup

Demo SQLite:

```bash
sqlite3 sklad.db ".backup 'backups/sklad-$(date +%Y%m%d-%H%M%S).db'"
```

Project files:

```bash
tar --exclude=.git --exclude=.venv --exclude=sklad.db -czf backups/sklad-files-$(date +%Y%m%d-%H%M%S).tar.gz .
```

Production PostgreSQL target:

- настроить регулярный `pg_dump` или PITR;
- хранить бэкапы отдельно от сервера приложения;
- проводить restore-test на отдельном окружении;
- сверять количество строк, остатки и последние записи audit log после восстановления.

## Rollback

- Остановить API.
- Вернуть предыдущий архив файлов.
- Восстановить базу из последнего проверенного backup.
- Запустить API и повторить health/readiness/smoke test.

## Блокеры production-сдачи по полному ТЗ

- PostgreSQL cutover rehearsal на staging с `scripts/sklad_postgres_reconcile.py`.
- Keycloak/OIDC вместо текущего HMAC/dev-header режима.
- Печатные формы PDF, ПКУ-журнал, штрихкоды/ценники.
- ЭДО/ЭЦП и интеграции с бухгалтерией/закупками.
- Мониторинг, алерты и проверенный restore process.
