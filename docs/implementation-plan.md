# Implementation Plan

## Increment 1

- Python/FastAPI backend skeleton.
- SQLite local persistence and pure service tests.
- Directories: categories, suppliers, warehouses, products.
- Batch-based receipt, quarantine status, stock balances.
- Manual write-off and reservation with free-balance checks.
- FEFO write-off by product.
- Internal transfers between warehouses/cabinets.
- Returns from departments and returns to suppliers.
- Reservation release and expiration job boundary.
- Draft/post documents for receipt and write-off workflows.
- Inventory lock.
- Inventory sessions: expected/factual counts, post and cancel.
- Low-stock notification generation.
- Append-only audit records.
- Bounded audit log API.

## Increment 2

- PostgreSQL + SQLAlchemy + Alembic migrations.
- Approval lifecycle around documents: draft, approved, posted, cancelled.
- Keycloak/OAuth2 integration and scoped RBAC.
- WebSocket stock events after committed transactions.
- Expiry notifications and scheduler/worker process for reminders and reservation expiration.

## Increment 3

- Transfer documents and approval workflow.
- Return documents with accounting integration hooks.
- Printable inventory and reconciliation documents.
- Returns, quarantine workflows and FEFO suggestions.
- ABC/XYZ analysis and reorder draft generation.
- Controlled substances journal and EDS signing boundaries.
