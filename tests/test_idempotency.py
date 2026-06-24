from unittest import TestCase
from datetime import UTC, datetime, timedelta

from app.domain.errors import ValidationError
from app.domain.errors import IdempotencyConflictError
from app.repositories.idempotency import (
    DuplicateIdempotencyKeyError,
    SQLiteIdempotencyRepository,
)
from app.services.idempotency import IdempotencyStore
from app.storage.sqlite import SQLiteDatabase


class IdempotencyStoreTest(TestCase):
    def setUp(self) -> None:
        self.database = SQLiteDatabase(":memory:")
        self.database.init_schema()
        self.store = IdempotencyStore(self.database)

    def test_first_claim_creates_processing_record(self) -> None:
        claim = self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        self.assertTrue(claim.created)
        self.assertEqual(claim.status, "processing")

    def test_successful_claim_replays_stored_response(self) -> None:
        self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )
        self.store.succeed(
            key="k1",
            actor_id="actor",
            response_status=201,
            response_body={"out_movement_id": 10, "in_movement_id": 11},
            resource_type="transfer",
            resource_id="10:11",
        )

        replay = self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        self.assertTrue(replay.replayed)
        self.assertEqual(replay.response_status, 201)
        self.assertEqual(replay.response_body, {"out_movement_id": 10, "in_movement_id": 11})
        self.assertEqual(replay.resource_type, "transfer")
        self.assertEqual(replay.resource_id, "10:11")

    def test_same_key_with_different_body_is_rejected(self) -> None:
        self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        with self.assertRaises(ValidationError):
            self.store.claim(
                key="k1",
                actor_id="actor",
                method="POST",
                path="/api/v1/transfers",
                request_hash="hash-2",
            )

    def test_same_key_with_different_path_is_rejected(self) -> None:
        self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        with self.assertRaises(ValidationError):
            self.store.claim(
                key="k1",
                actor_id="actor",
                method="POST",
                path="/api/v1/write-offs",
                request_hash="hash-1",
            )

    def test_same_key_is_scoped_by_actor(self) -> None:
        self.store.claim(
            key="k1",
            actor_id="actor-1",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        claim = self.store.claim(
            key="k1",
            actor_id="actor-2",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-2",
        )

        self.assertTrue(claim.created)
        self.assertEqual(claim.actor_id, "actor-2")

    def test_fresh_processing_claim_blocks_duplicate_execution(self) -> None:
        self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        with self.assertRaises(IdempotencyConflictError):
            self.store.claim(
                key="k1",
                actor_id="actor",
                method="POST",
                path="/api/v1/transfers",
                request_hash="hash-1",
            )

    def test_stale_processing_claim_can_be_reclaimed(self) -> None:
        self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )
        stale_locked_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE idempotency_keys
                SET locked_at = ?
                WHERE actor_id = ? AND key = ?
                """,
                (stale_locked_at, "actor", "k1"),
            )

        claim = self.store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
            processing_timeout_seconds=60,
        )

        self.assertTrue(claim.created)
        self.assertEqual(claim.status, "processing")

    def test_store_accepts_repository_boundary(self) -> None:
        store = IdempotencyStore(SQLiteIdempotencyRepository(self.database))

        claim = store.claim(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
        )

        self.assertTrue(claim.created)
        self.assertEqual(claim.status, "processing")

    def test_sqlite_repository_rejects_duplicate_processing_key(self) -> None:
        repository = SQLiteIdempotencyRepository(self.database)
        repository.create_processing(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
            locked_at=datetime.now(UTC).isoformat(),
        )

        with self.assertRaises(DuplicateIdempotencyKeyError):
            repository.create_processing(
                key="k1",
                actor_id="actor",
                method="POST",
                path="/api/v1/transfers",
                request_hash="hash-1",
                locked_at=datetime.now(UTC).isoformat(),
            )

    def test_sqlite_repository_round_trips_json_response_body(self) -> None:
        repository = SQLiteIdempotencyRepository(self.database)
        repository.create_processing(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
            locked_at=datetime.now(UTC).isoformat(),
        )

        record = repository.mark_succeeded(
            key="k1",
            actor_id="actor",
            response_status=201,
            response_body={"out_movement_id": 10, "nested": {"ok": True}},
            resource_type="transfer",
            resource_id="10:11",
        )
        fetched = repository.get(key="k1", actor_id="actor")

        self.assertEqual(record.response_body, {"out_movement_id": 10, "nested": {"ok": True}})
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.response_body, {"out_movement_id": 10, "nested": {"ok": True}})

    def test_refresh_processing_lock_only_updates_processing_records(self) -> None:
        repository = SQLiteIdempotencyRepository(self.database)
        repository.create_processing(
            key="k1",
            actor_id="actor",
            method="POST",
            path="/api/v1/transfers",
            request_hash="hash-1",
            locked_at=datetime.now(UTC).isoformat(),
        )

        self.assertTrue(
            repository.refresh_processing_lock(
                key="k1",
                actor_id="actor",
                locked_at=datetime.now(UTC).isoformat(),
            )
        )

        repository.mark_succeeded(
            key="k1",
            actor_id="actor",
            response_status=201,
            response_body={"ok": True},
        )

        self.assertFalse(
            repository.refresh_processing_lock(
                key="k1",
                actor_id="actor",
                locked_at=datetime.now(UTC).isoformat(),
            )
        )
