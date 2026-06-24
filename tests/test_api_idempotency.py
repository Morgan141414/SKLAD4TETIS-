from unittest import TestCase

from app.domain.errors import IdempotencyConflictError, ValidationError
from app.services.idempotency import IdempotencyStore, run_idempotent
from app.storage.sqlite import SQLiteDatabase


class APIIdempotencyHelperTest(TestCase):
    def setUp(self) -> None:
        self.database = SQLiteDatabase(":memory:")
        self.database.init_schema()
        self.store = IdempotencyStore(self.database)

    def test_replay_returns_stored_response_without_calling_operation(self) -> None:
        calls = 0

        def operation() -> dict:
            nonlocal calls
            calls += 1
            return {"id": 7, "movement_id": 9}

        first, first_replayed = run_idempotent(
            idempotency_key="k1",
            store=self.store,
            actor_id="actor",
            method="POST",
            path="/api/v1/write-offs",
            payload={"batch_id": 1, "quantity": "2"},
            response_status=201,
            resource_type="stock_movement",
            operation=operation,
        )
        second, second_replayed = run_idempotent(
            idempotency_key="k1",
            store=self.store,
            actor_id="actor",
            method="POST",
            path="/api/v1/write-offs",
            payload={"batch_id": 1, "quantity": "2"},
            response_status=201,
            resource_type="stock_movement",
            operation=operation,
        )

        self.assertFalse(first_replayed)
        self.assertTrue(second_replayed)
        self.assertEqual(first, second)
        self.assertEqual(calls, 1)

    def test_same_key_with_different_payload_is_conflict(self) -> None:
        run_idempotent(
            idempotency_key="k1",
            store=self.store,
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            payload={"batch_id": 1, "quantity": "2"},
            response_status=201,
            resource_type="transfer",
            operation=lambda: {"out_movement_id": 1, "in_movement_id": 2},
        )

        with self.assertRaises(IdempotencyConflictError):
            run_idempotent(
                idempotency_key="k1",
                store=self.store,
                actor_id="actor",
                method="POST",
                path="/api/v1/transfers",
                payload={"batch_id": 1, "quantity": "3"},
                response_status=201,
                resource_type="transfer",
                operation=lambda: {"out_movement_id": 3, "in_movement_id": 4},
            )

    def test_failed_operation_marks_key_failed_and_blocks_replay(self) -> None:
        def operation() -> dict:
            raise ValidationError("boom")

        with self.assertRaises(ValidationError):
            run_idempotent(
                idempotency_key="k1",
                store=self.store,
                actor_id="actor",
                method="POST",
                path="/api/v1/transfers",
                payload={"batch_id": 1},
                response_status=201,
                resource_type="transfer",
                operation=operation,
            )

        with self.assertRaises(IdempotencyConflictError):
            run_idempotent(
                idempotency_key="k1",
                store=self.store,
                actor_id="actor",
                method="POST",
                path="/api/v1/transfers",
                payload={"batch_id": 1},
                response_status=201,
                resource_type="transfer",
                operation=lambda: {"out_movement_id": 1, "in_movement_id": 2},
            )
