# Backup And Restore Runbook

Этот документ описывает минимальный порядок резервного копирования и восстановления склада.

## Цели

- **RPO demo:** потеря данных не больше периода между ручными backup.
- **RPO production target:** согласуется с организацией, рекомендуемый старт - 15 минут при PostgreSQL PITR.
- **RTO demo:** восстановление за 30-60 минут при наличии архива файлов и базы.
- **RTO production target:** подтверждается restore-test на отдельном окружении.

## Demo SQLite Backup

Остановите запись в систему или выполняйте backup в момент простоя.

```bash
mkdir -p backups
sqlite3 sklad.db ".backup 'backups/sklad-$(date +%Y%m%d-%H%M%S).db'"
tar --exclude=.git --exclude=.venv --exclude=sklad.db -czf backups/sklad-files-$(date +%Y%m%d-%H%M%S).tar.gz .
```

Проверка:

```bash
sqlite3 backups/sklad-YYYYMMDD-HHMMSS.db "PRAGMA integrity_check;"
```

## Demo SQLite Restore

```bash
systemctl stop sklad || true
cp backups/sklad-YYYYMMDD-HHMMSS.db sklad.db
python3 -m unittest discover -s tests -v
uvicorn app.main:app --host 0.0.0.0 --port 8120
```

Проверить:

```bash
curl -sS http://127.0.0.1:8120/api/v1/health
curl -sS http://127.0.0.1:8120/api/v1/health/ready
```

## Production PostgreSQL Target

PostgreSQL runtime adapter и миграционные инструменты подготовлены, но production cutover выполняется только по `docs/postgresql-migration-runbook.md`. Для production-режима:

- использовать `pg_dump` для логических backup перед релизами;
- использовать WAL/PITR для регулярного восстановления на момент времени;
- хранить backup вне сервера приложения;
- проверять restore на отдельной базе по расписанию;
- фиксировать результат restore-test в журнале эксплуатации.

Пример логического backup:

```bash
pg_dump "$SKLAD_DATABASE_URL" --format=custom --file "backups/sklad-$(date +%Y%m%d-%H%M%S).dump"
```

Пример restore-test:

```bash
createdb sklad_restore_test
pg_restore --dbname=sklad_restore_test backups/sklad-YYYYMMDD-HHMMSS.dump
```

## Reconciliation После Restore

После восстановления проверьте:

- количество товаров, партий, остатков, документов, движений;
- отсутствие отрицательных остатков и резервов;
- последние записи `audit_log`;
- health/readiness;
- smoke test: приход -> карточка партии -> списание/перемещение -> CSV экспорт.

Для сверки SQLite snapshot с PostgreSQL после миграции используйте:

```bash
scripts/sklad_postgres_reconcile.py backups/sklad-cutover-YYYYMMDD-HHMMSS.db "$SKLAD_DATABASE_URL" --json
```

## Что Нельзя Делать

- Не хранить единственный backup на том же диске, где лежит база.
- Не проверять backup только фактом создания файла.
- Не включать production без заранее проверенного restore.
- Не редактировать `audit_log` вручную.
