import os
from unittest import TestCase
from unittest.mock import patch


class _PostgresConnectionWithoutPath:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, query: str) -> "_PostgresConnectionWithoutPath":
        if query != "SELECT 1":
            raise AssertionError(f"unexpected readiness query: {query}")
        return self

    def fetchone(self) -> dict[str, int]:
        return {"?column?": 1}

    def close(self) -> None:
        self.closed = True


class _PostgresDatabaseWithoutPath:
    connection = _PostgresConnectionWithoutPath()

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def connect(self) -> _PostgresConnectionWithoutPath:
        return self.connection


class PostgreSQLRuntimeReadinessTest(TestCase):
    def setUp(self) -> None:
        try:
            from app.api import dependencies
            from app.core.config import get_settings
        except ModuleNotFoundError as error:
            self.skipTest(f"runtime dependencies are not installed: {error.name}")
        self.dependencies = dependencies
        self.get_settings = get_settings

    def tearDown(self) -> None:
        if hasattr(self, "get_settings"):
            self.get_settings.cache_clear()
        if hasattr(self, "dependencies"):
            self.dependencies._database = None

    def _reset_settings(self) -> None:
        self.get_settings.cache_clear()
        self.dependencies._database = None

    def test_sqlite_readiness_still_uses_sqlite_runtime(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SKLAD_DEPLOYMENT_MODE": "demo",
                "SKLAD_DATABASE_BACKEND": "sqlite",
                "SKLAD_DATABASE_URL": "sqlite:///:memory:",
            },
        ):
            self._reset_settings()

            readiness = self.dependencies.get_database_readiness()

        self.assertEqual(readiness["status"], "ok")
        self.assertEqual(readiness["backend"], "sqlite")
        self.assertEqual(readiness["detail"], "ready")

    def test_postgresql_readiness_reports_connection_error_until_database_is_reachable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SKLAD_DEPLOYMENT_MODE": "staging",
                "SKLAD_DATABASE_BACKEND": "postgresql",
                "SKLAD_DATABASE_URL": "postgresql+psycopg://sklad:secret@db/sklad",
            },
        ):
            self._reset_settings()

            readiness = self.dependencies.get_database_readiness()

        self.assertEqual(readiness["status"], "error")
        self.assertEqual(readiness["backend"], "postgresql")

    def test_postgresql_database_dependency_selects_postgresql_adapter(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SKLAD_DEPLOYMENT_MODE": "staging",
                "SKLAD_DATABASE_BACKEND": "postgresql",
                "SKLAD_DATABASE_URL": "postgresql://sklad:secret@db/sklad",
            },
        ), patch("app.api.dependencies.PostgresDatabase") as database_class:
            self._reset_settings()

            database = self.dependencies.get_database()

        self.assertEqual(database, database_class.return_value)
        database_class.assert_called_once_with("postgresql://sklad:secret@db/sklad")

    def test_postgresql_readiness_does_not_require_sqlite_path_contract(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SKLAD_DEPLOYMENT_MODE": "staging",
                "SKLAD_DATABASE_BACKEND": "postgresql",
                "SKLAD_DATABASE_URL": "postgresql://sklad:secret@db/sklad",
            },
        ), patch("app.api.dependencies.PostgresDatabase", _PostgresDatabaseWithoutPath):
            self._reset_settings()
            _PostgresDatabaseWithoutPath.connection = _PostgresConnectionWithoutPath()

            readiness = self.dependencies.get_database_readiness()

        self.assertEqual(readiness["status"], "ok")
        self.assertEqual(readiness["backend"], "postgresql")
        self.assertEqual(readiness["detail"], self.dependencies.POSTGRESQL_RUNTIME_ADAPTER_DETAIL)
        self.assertTrue(_PostgresDatabaseWithoutPath.connection.closed)

    def test_backend_url_mismatch_fails_before_runtime_selection(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SKLAD_DEPLOYMENT_MODE": "demo",
                "SKLAD_DATABASE_BACKEND": "sqlite",
                "SKLAD_DATABASE_URL": "postgresql://sklad:secret@db/sklad",
            },
        ):
            self._reset_settings()

            readiness = self.dependencies.get_database_readiness()
            with self.assertRaises(RuntimeError) as context:
                self.dependencies.get_database()

        self.assertEqual(readiness["status"], "error")
        self.assertEqual(readiness["backend"], "sqlite")
        self.assertIn("does not match", readiness["detail"])
        self.assertIn("does not match", str(context.exception))

    def test_sqlite_is_rejected_outside_demo_mode(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SKLAD_DEPLOYMENT_MODE": "staging",
                "SKLAD_DATABASE_BACKEND": "sqlite",
                "SKLAD_DATABASE_URL": "sqlite:///:memory:",
            },
        ):
            self._reset_settings()

            readiness = self.dependencies.get_database_readiness()
            with self.assertRaises(RuntimeError) as context:
                self.dependencies.get_database()

        self.assertEqual(readiness["status"], "error")
        self.assertEqual(readiness["backend"], "sqlite")
        self.assertEqual(readiness["mode"], "staging")
        self.assertIn("SQLite is allowed only", readiness["detail"])
        self.assertIn("SQLite is allowed only", str(context.exception))
