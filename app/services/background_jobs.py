import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Callable

from app.services.warehouse import WarehouseService
from app.services.telegram_notifier import notify_critical

if TYPE_CHECKING:
    from app.storage.postgresql import PostgresDatabase

logger = logging.getLogger(__name__)

# PostgreSQL session-level advisory lock key (arbitrary unique constant for this service)
_ADVISORY_LOCK_KEY = 736471  # "sklad" in decimal-ish


@dataclass(frozen=True)
class BackgroundJobResult:
    expired_reservations: int = 0
    low_stock_notifications: int = 0
    expiry_notifications: int = 0
    abc_xyz_runs: int = 0
    quarantine_notifications: int = 0
    quarantine_overdue_notifications: int = 0
    supplier_contract_notifications: int = 0
    auto_purchase_requests: int = 0
    errors: list[str] = field(default_factory=list)
    ran_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class WarehouseBackgroundJobs:
    def __init__(
        self,
        service_factory: Callable[[], WarehouseService],
        *,
        expiry_days: int = 30,
        actor_id: str = "system-scheduler",
        db: "PostgresDatabase | None" = None,
        telegram_bot_token: str | None = None,
        telegram_chat_id: str | None = None,
    ) -> None:
        if expiry_days < 0:
            raise ValueError("expiry_days cannot be negative")
        if not actor_id.strip():
            raise ValueError("actor_id cannot be empty")
        self.service_factory = service_factory
        self.expiry_days = expiry_days
        self.actor_id = actor_id
        self._db = db
        self._tg_token = telegram_bot_token
        self._tg_chat = telegram_chat_id

    def run_once(self) -> BackgroundJobResult | None:
        """Run all background jobs. Returns None if another process holds the lock."""
        started = datetime.now(UTC)
        log_id: int | None = None

        conn = None
        if self._db is not None:
            try:
                conn = self._db.connect()
                # Session-level advisory lock: non-blocking, returns bool
                conn._connection.autocommit = True
                row = conn._connection.execute(
                    "SELECT pg_try_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,)
                ).fetchone()
                if row and not row["pg_try_advisory_lock"]:
                    logger.info("Background jobs skipped: another process holds the lock")
                    conn.close()
                    return None
            except Exception:
                logger.exception("Could not acquire advisory lock; running without lock")
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = None

        # Insert running record
        if conn is not None and self._db is not None:
            try:
                conn._connection.autocommit = False
                row2 = conn._connection.execute(
                    "INSERT INTO job_log (job_name, status, started_at) VALUES (%s, %s, %s) RETURNING id",
                    ("warehouse_background_jobs", "running", started),
                ).fetchone()
                if row2:
                    log_id = int(row2["id"])
                conn._connection.commit()
            except Exception:
                logger.exception("Could not write job_log start record")
                try:
                    conn._connection.rollback()
                except Exception:
                    pass

        result = self._do_run()
        finished = datetime.now(UTC)
        duration_ms = int((finished - started).total_seconds() * 1000)

        status = "failed" if result.errors else "done"

        if conn is not None and log_id is not None:
            try:
                conn._connection.autocommit = False
                conn._connection.execute(
                    """UPDATE job_log
                       SET status=%s, finished_at=%s, duration_ms=%s,
                           result_json=%s, error_text=%s
                     WHERE id=%s""",
                    (
                        status,
                        finished,
                        duration_ms,
                        json.dumps(asdict(result)),
                        "\n".join(result.errors) or None,
                        log_id,
                    ),
                )
                conn._connection.commit()
            except Exception:
                logger.exception("Could not update job_log finish record")
                try:
                    conn._connection.rollback()
                except Exception:
                    pass

        if conn is not None:
            try:
                # Release session advisory lock then close
                conn._connection.autocommit = True
                conn._connection.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
                conn.close()
            except Exception:
                logger.exception("Could not release advisory lock")

        return result

    def _do_run(self) -> BackgroundJobResult:
        service = self.service_factory()
        errors: list[str] = []
        expired_reservations = 0
        low_stock_notifications = 0
        expiry_notifications = 0
        abc_xyz_runs = 0

        try:
            expired_reservations = len(service.expire_reservations(actor_id=self.actor_id))
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to expire overdue reservations")
            errors.append(f"expire_reservations: {error}")

        try:
            low_stock_notifications = len(service.generate_low_stock_notifications())
            if low_stock_notifications > 0:
                notify_critical(self._tg_token, self._tg_chat,
                    "Мало остатка",
                    f"Сгенерировано {low_stock_notifications} предупреждений о малом остатке.")
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to generate low stock notifications")
            errors.append(f"generate_low_stock_notifications: {error}")

        try:
            expiry_notifications = len(
                service.generate_expiry_notifications(days=self.expiry_days)
            )
            if expiry_notifications > 0:
                notify_critical(self._tg_token, self._tg_chat,
                    "Срок годности",
                    f"Истекает срок у {expiry_notifications} позиций.")
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to generate expiry notifications")
            errors.append(f"generate_expiry_notifications: {error}")

        try:
            before = service.count_abc_xyz_runs()
            service.save_monthly_abc_xyz_analysis_snapshot(actor_id=self.actor_id)
            after = service.count_abc_xyz_runs()
            abc_xyz_runs = max(0, after - before)
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to save monthly ABC/XYZ analysis")
            errors.append(f"save_monthly_abc_xyz_analysis_snapshot: {error}")

        quarantine_notifications = 0
        try:
            quarantine_notifications = len(
                service.generate_quarantine_notifications(days=3)
            )
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to generate quarantine notifications")
            errors.append(f"generate_quarantine_notifications: {error}")

        quarantine_overdue_notifications = 0
        try:
            quarantine_overdue_notifications = len(
                service.generate_quarantine_review_overdue_notifications(days=7)
            )
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to generate quarantine overdue notifications")
            errors.append(f"generate_quarantine_review_overdue_notifications: {error}")

        supplier_contract_notifications = 0
        try:
            supplier_contract_notifications = len(
                service.generate_supplier_contract_expiry_notifications(days=30)
            )
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to generate supplier contract expiry notifications")
            errors.append(f"generate_supplier_contract_expiry_notifications: {error}")

        auto_purchase_requests = 0
        try:
            warehouses = service.list_warehouses()
            for wh in warehouses:
                try:
                    created = service.generate_purchase_requests(
                        warehouse_id=wh["id"], actor_id=self.actor_id
                    )
                    auto_purchase_requests += len(created)
                except Exception:  # pragma: no cover
                    pass
        except Exception as error:  # pragma: no cover
            logger.exception("Failed to generate auto purchase requests")
            errors.append(f"generate_purchase_requests: {error}")

        return BackgroundJobResult(
            expired_reservations=expired_reservations,
            low_stock_notifications=low_stock_notifications,
            expiry_notifications=expiry_notifications,
            abc_xyz_runs=abc_xyz_runs,
            quarantine_notifications=quarantine_notifications,
            quarantine_overdue_notifications=quarantine_overdue_notifications,
            supplier_contract_notifications=supplier_contract_notifications,
            auto_purchase_requests=auto_purchase_requests,
            errors=errors,
        )


class PeriodicJobRunner:
    def __init__(
        self,
        jobs: WarehouseBackgroundJobs,
        *,
        interval_seconds: int = 3600,
    ) -> None:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be at least 1")
        self.jobs = jobs
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self.last_result: BackgroundJobResult | None = None
        self.last_ran_at: str | None = None
        self.is_running: bool = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if not self._task:
            return
        self._stopping.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(self) -> BackgroundJobResult | None:
        if self._run_lock.locked():
            return None
        async with self._run_lock:
            self.is_running = True
            try:
                result = await asyncio.to_thread(self.jobs.run_once)
            finally:
                self.is_running = False
            if result is not None:
                self.last_result = result
                self.last_ran_at = getattr(result, "ran_at", None)
            return result

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            result = await self.run_once()
            if result:
                logger.info(
                    "Background warehouse jobs finished: expired_reservations=%s "
                    "low_stock_notifications=%s expiry_notifications=%s "
                    "abc_xyz_runs=%s errors=%s",
                    result.expired_reservations,
                    result.low_stock_notifications,
                    result.expiry_notifications,
                    result.abc_xyz_runs,
                    len(result.errors),
                )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue
