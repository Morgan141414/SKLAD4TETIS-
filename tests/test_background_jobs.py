import asyncio
from unittest import TestCase
from unittest.mock import patch

from app.services.background_jobs import PeriodicJobRunner, WarehouseBackgroundJobs


class FakeWarehouseService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.abc_xyz_run_count = 0

    def expire_reservations(self, actor_id: str = "system", warehouse_id: int | None = None):
        self.calls.append(("expire_reservations", actor_id))
        return [{"id": 1}, {"id": 2}]

    def generate_low_stock_notifications(self, warehouse_id: int | None = None):
        self.calls.append(("generate_low_stock_notifications", warehouse_id))
        return [{"id": 10}]

    def generate_expiry_notifications(self, days: int = 30, warehouse_id: int | None = None):
        self.calls.append(("generate_expiry_notifications", days))
        return [{"id": 20}, {"id": 21}, {"id": 22}]

    def count_abc_xyz_runs(self, warehouse_id: int | None = None) -> int:
        self.calls.append(("count_abc_xyz_runs", warehouse_id))
        return self.abc_xyz_run_count

    def save_monthly_abc_xyz_analysis_snapshot(self, actor_id: str = "system-scheduler"):
        self.calls.append(("save_monthly_abc_xyz_analysis_snapshot", actor_id))
        self.abc_xyz_run_count += 1
        return {"id": self.abc_xyz_run_count}

    def generate_quarantine_notifications(self, days: int = 3, warehouse_id=None):
        self.calls.append(("generate_quarantine_notifications", days))
        return []

    def generate_quarantine_review_overdue_notifications(self, days: int = 7):
        self.calls.append(("generate_quarantine_review_overdue_notifications", days))
        return []

    def generate_supplier_contract_expiry_notifications(self, days: int = 30):
        self.calls.append(("generate_supplier_contract_expiry_notifications", days))
        return []

    def list_warehouses(self):
        self.calls.append(("list_warehouses", None))
        return []

    def generate_purchase_requests(self, warehouse_id: int, actor_id: str = "system"):
        self.calls.append(("generate_purchase_requests", warehouse_id))
        return []


class FailingWarehouseService(FakeWarehouseService):
    def generate_low_stock_notifications(self, warehouse_id: int | None = None):
        raise RuntimeError("low-stock failed")


class BackgroundJobsTest(TestCase):
    def test_run_once_executes_periodic_warehouse_jobs(self) -> None:
        service = FakeWarehouseService()
        jobs = WarehouseBackgroundJobs(
            lambda: service,
            expiry_days=45,
            actor_id="scheduler-test",
        )

        result = jobs.run_once()

        self.assertEqual(result.expired_reservations, 2)
        self.assertEqual(result.low_stock_notifications, 1)
        self.assertEqual(result.expiry_notifications, 3)
        self.assertEqual(result.abc_xyz_runs, 1)
        self.assertEqual(result.errors, [])
        expected_calls = [
            ("expire_reservations", "scheduler-test"),
            ("generate_low_stock_notifications", None),
            ("generate_expiry_notifications", 45),
            ("count_abc_xyz_runs", None),
            ("save_monthly_abc_xyz_analysis_snapshot", "scheduler-test"),
            ("count_abc_xyz_runs", None),
            ("generate_quarantine_notifications", 3),
            ("generate_quarantine_review_overdue_notifications", 7),
            ("generate_supplier_contract_expiry_notifications", 30),
            ("list_warehouses", None),
        ]
        self.assertEqual(service.calls, expected_calls)

    def test_run_once_continues_after_one_job_failure(self) -> None:
        service = FailingWarehouseService()
        jobs = WarehouseBackgroundJobs(lambda: service, expiry_days=30)

        with patch("app.services.background_jobs.logger.exception") as log_exception:
            result = jobs.run_once()

        self.assertEqual(result.expired_reservations, 2)
        self.assertEqual(result.low_stock_notifications, 0)
        self.assertEqual(result.expiry_notifications, 3)
        self.assertEqual(result.abc_xyz_runs, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("generate_low_stock_notifications", result.errors[0])
        self.assertEqual(log_exception.call_count, 1)

    def test_periodic_runner_rejects_overlapping_manual_runs(self) -> None:
        class SlowJobs:
            def run_once(self):
                import time

                time.sleep(0.05)
                return "done"

        async def scenario():
            runner = PeriodicJobRunner(SlowJobs(), interval_seconds=1)  # type: ignore[arg-type]
            first = asyncio.create_task(runner.run_once())
            await asyncio.sleep(0)
            second = await runner.run_once()
            first_result = await first
            return first_result, second

        first_result, second_result = asyncio.run(scenario())

        self.assertEqual(first_result, "done")
        self.assertIsNone(second_result)

    def test_rejects_invalid_settings(self) -> None:
        with self.assertRaises(ValueError):
            WarehouseBackgroundJobs(lambda: FakeWarehouseService(), expiry_days=-1)

        with self.assertRaises(ValueError):
            WarehouseBackgroundJobs(lambda: FakeWarehouseService(), actor_id=" ")

        with self.assertRaises(ValueError):
            PeriodicJobRunner(WarehouseBackgroundJobs(lambda: FakeWarehouseService()), interval_seconds=0)
