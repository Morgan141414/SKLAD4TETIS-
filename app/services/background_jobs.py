import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from app.services.warehouse import WarehouseService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackgroundJobResult:
    expired_reservations: int = 0
    low_stock_notifications: int = 0
    expiry_notifications: int = 0
    abc_xyz_runs: int = 0
    errors: list[str] = field(default_factory=list)
    ran_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class WarehouseBackgroundJobs:
    def __init__(
        self,
        service_factory: Callable[[], WarehouseService],
        *,
        expiry_days: int = 30,
        actor_id: str = "system-scheduler",
    ) -> None:
        if expiry_days < 0:
            raise ValueError("expiry_days cannot be negative")
        if not actor_id.strip():
            raise ValueError("actor_id cannot be empty")
        self.service_factory = service_factory
        self.expiry_days = expiry_days
        self.actor_id = actor_id

    def run_once(self) -> BackgroundJobResult:
        service = self.service_factory()
        errors: list[str] = []
        expired_reservations = 0
        low_stock_notifications = 0
        expiry_notifications = 0
        abc_xyz_runs = 0

        try:
            expired_reservations = len(service.expire_reservations(actor_id=self.actor_id))
        except Exception as error:  # pragma: no cover - logging branch is covered by result tests
            logger.exception("Failed to expire overdue reservations")
            errors.append(f"expire_reservations: {error}")

        try:
            low_stock_notifications = len(service.generate_low_stock_notifications())
        except Exception as error:  # pragma: no cover - logging branch is covered by result tests
            logger.exception("Failed to generate low stock notifications")
            errors.append(f"generate_low_stock_notifications: {error}")

        try:
            expiry_notifications = len(
                service.generate_expiry_notifications(days=self.expiry_days)
            )
        except Exception as error:  # pragma: no cover - logging branch is covered by result tests
            logger.exception("Failed to generate expiry notifications")
            errors.append(f"generate_expiry_notifications: {error}")

        try:
            before = service.count_abc_xyz_runs()
            service.save_monthly_abc_xyz_analysis_snapshot(actor_id=self.actor_id)
            after = service.count_abc_xyz_runs()
            abc_xyz_runs = max(0, after - before)
        except Exception as error:  # pragma: no cover - logging branch is covered by result tests
            logger.exception("Failed to save monthly ABC/XYZ analysis")
            errors.append(f"save_monthly_abc_xyz_analysis_snapshot: {error}")

        return BackgroundJobResult(
            expired_reservations=expired_reservations,
            low_stock_notifications=low_stock_notifications,
            expiry_notifications=expiry_notifications,
            abc_xyz_runs=abc_xyz_runs,
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
            return await asyncio.to_thread(self.jobs.run_once)

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
