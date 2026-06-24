# Database Layer

This directory contains the production database foundation.

Current runtime still uses the SQLite adapter in `app/storage/sqlite.py` so that existing business tests and the running demo stay stable. The target production path is PostgreSQL + SQLAlchemy + Alembic.

Files:

- `sql/0001_initial_postgresql.sql`: PostgreSQL DDL matching the current domain model and adding production tables for idempotency and outbox events.
- `migrations/`: Alembic migration environment. The first migration executes the reviewed PostgreSQL baseline SQL.
- `session.py`: SQLAlchemy engine/session factory for the future PostgreSQL runtime.
- `uow.py`: minimal Unit of Work boundary for future repository-based service methods.

## PostgreSQL Runtime Gate

`SKLAD_DATABASE_BACKEND=postgresql` is intentionally fail-fast in this service build. The
PostgreSQL schema, Alembic migration, SQLAlchemy session factory, and idempotency repository are
present, but `WarehouseService` still depends on the SQLite storage adapter and sqlite parameter
style. Readiness reports:

- `status=error`
- `runtime_adapter=disabled`
- `required_revision=0001_initial_postgresql`
- `migration_command=alembic upgrade head`

This keeps production deployments from silently starting with a partially wired PostgreSQL runtime.
Before switching traffic to PostgreSQL, run the Alembic baseline against the target database and add
PostgreSQL-backed repositories for the warehouse service operations.

Next steps:

1. Finish SQLAlchemy models for the remaining DDL tables.
2. Add PostgreSQL repositories and connect write operations through Unit of Work.
3. Run `alembic upgrade head` against the target PostgreSQL database.
4. Enable runtime selection behind `SKLAD_DATABASE_BACKEND=postgresql`.
5. Add PostgreSQL integration tests in CI.
