# Sklad Service

Python/FastAPI backend for a medical warehouse service.

Implemented first increment:

- Product, category, supplier, warehouse directories.
- Batch accounting with expiration dates, quarantine and blocked batches.
- Stock balance tracking with free balance calculation.
- Direct receipts, write-offs and reservations.
- Draft/post stock documents for receipts and write-offs.
- FEFO write-off by product across available batches.
- Internal transfers between warehouses/cabinets with batch traceability.
- Returns from departments and returns to original supplier.
- Manual and automatic release of expired reservations.
- Inventory lock that blocks stock movements while inventory is in progress.
- Inventory sessions with expected/factual counts, shortage/surplus posting and cancellation.
- Low-stock and expiry in-app notifications.
- Optional background jobs for expired reservations and attention notifications.
- ABC/XYZ analysis with reorder recommendations.
- Append-only audit log for business actions.
- Audit log API.
- RBAC foundation with roles, permissions and warehouse scope tests.

Production planning documents:

- `docs/user-guide.md`
- `docs/deployment-checklist.md`
- `docs/backup-restore.md`
- `docs/reporting-and-exports.md`
- `docs/release-checklist.md`
- `docs/full-product-roadmap.md`
- `docs/product-gap-backlog.md`
- `docs/production-migration-plan.md`
- `docs/quality-gates.md`
- `docs/production-architecture-decisions.md`
- `docs/postgresql-schema-notes.md`
- `docs/service-decomposition-plan.md`
- `docs/api-contract-plan.md`

Production foundation files:

- `Dockerfile`
- `docker-compose.yml`
- `app/db/sql/0001_initial_postgresql.sql`
- FastAPI routes and pure Python service tests.

Run locally after installing Python dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# For local/demo header auth only. Production must use real JWT/OIDC auth.
printf '\nSKLAD_DEV_AUTH_ENABLED=true\n' >> .env
uvicorn app.main:app --reload
```

Optional background checks:

```bash
SKLAD_BACKGROUND_JOBS_ENABLED=true
SKLAD_BACKGROUND_JOBS_INTERVAL_SECONDS=3600
SKLAD_BACKGROUND_JOBS_EXPIRY_DAYS=30
SKLAD_BACKGROUND_JOBS_ACTOR_ID=system-scheduler
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

Health checks:

```text
GET /api/v1/health
GET /api/v1/health/ready
```

Frontend:

```text
http://127.0.0.1:8000/app/
```

Operational exports are available in the frontend as CSV downloads for balances, stock documents, movements, ABC/XYZ analytics and audit log.

Runtime modes:

- Demo/local may use SQLite with `SKLAD_DEPLOYMENT_MODE=demo`.
- Staging/production must use PostgreSQL; the app refuses SQLite when `SKLAD_DEPLOYMENT_MODE` is `staging` or `production`.
- Default `docker-compose.yml` starts the API on PostgreSQL and runs `alembic upgrade head` before Uvicorn.
- SQLite demo compose is still available through `docker compose -f docker-compose.demo.yml up --build`.

Production cutover from an existing SQLite database must go through the migration runbook: SQLite backup, preflight, PostgreSQL load, reconciliation and smoke tests. See `docs/postgresql-migration-runbook.md`.

Run tests:

```bash
pytest
```
