# Architecture Notes

The first increment is intentionally backend-first and Python-only.

## Layers

- `app/domain`: enums, schemas and business exceptions.
- `app/storage`: SQLite persistence for local development/tests plus PostgreSQL runtime adapter for migration rehearsal and production target.
- `app/services`: business operations and invariants.
- `app/api`: FastAPI routes and dependency wiring.
- `scripts`: operational helpers, including the local temperature/humidity sensor bridge and hardware diagnostics.

## MVP business invariants

- Warehouse movements are rejected when `inventory_lock` is enabled.
- Quarantine and blocked batches cannot be issued or reserved.
- Controlled-substance write-offs require patient, doctor, medical record and a second approver; the confirmation is stored on the stock movement and visible in the controlled-substance ledger.
- Free stock equals total quantity minus reserved quantity.
- Write-off and reservation use only free stock.
- FEFO write-off chooses available batches by earliest expiration date.
- Transfers move free batch quantity between warehouses atomically and create paired movement records.
- Department returns reuse the same atomic stock movement path; supplier returns reduce free stock and validate the original supplier.
- Repacking is handled as a stock document: posting consumes the source batch, creates a child batch, records `repack_out`/`repack_in` movements and stores the parent-child transformation with losses and conversion factor.
- Batch recall blocks the affected batch, records a recall entry, writes recall audit events per affected warehouse and creates unread recall notifications for warehouses with remaining stock.
- Released or expired reservations restore reserved quantity to free stock.
- Draft stock documents do not affect balances until they are posted.
- Approved stock documents record managerial approval but still do not affect balances until posting.
- Stock document posting is idempotent and atomic.
- Inventory sessions lock a warehouse, snapshot expected balances and post shortage/surplus corrections atomically.
- Inventory cannot post factual quantity below already reserved quantity.
- All mutating operations append records to `audit_log`.
- Low-stock notifications are deduplicated while unread.
- Audit log is exposed through a bounded read endpoint for operational review.
- Storage condition sensors are registered per warehouse/cabinet; readings are journaled with threshold-based `ok`/`warning` status.

## Current Hardware Integration Status

- SKLAD has API, database tables, frontend screen and scripts for temperature/humidity readings.
- The local CH340 device is visible at `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`.
- Diagnostics tried passive serial, Arduino-style DTR/RTS reset, command probes and safe Modbus RTU reads.
- The device currently returns no valid temperature/humidity payload; the remaining blocker is the controller protocol, firmware or physical wiring.
- The detailed runbook is in `docs/sensor-controller-diagnostics.md`.

## Next production steps

- Rehearse SQLite -> PostgreSQL migration with backup, preflight, load, reconciliation and smoke tests before production cutover.
- Add Keycloak/OAuth2 JWT verification and route-level RBAC.
- Add WebSocket balance broadcaster backed by Redis pub/sub.
- Add monthly ABC/XYZ jobs and reorder draft generation.
- Add printed forms, approvals and reusable recipes for repacking.
- Add immutable audit storage policy and operational dashboards.
