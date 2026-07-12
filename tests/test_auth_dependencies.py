import importlib.util
import unittest
from unittest import TestCase
from unittest.mock import patch

from app.security.rbac import Role
from app.security.tokens import encode_jwt_hs256


HAS_API_DEPS = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("pydantic_settings") is not None
)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI settings dependencies are not installed")
class AuthDependencyTest(TestCase):
    def test_production_mode_rejects_dev_headers_without_bearer_token(self) -> None:
        from fastapi import HTTPException

        from app.api.dependencies import get_actor_context
        from app.core.config import Settings

        settings = Settings(
            public_access_enabled=False,
            dev_auth_enabled=False,
            jwt_hmac_secret="secret",
            jwt_issuer=None,
            jwt_audience=None,
            oidc_enabled=False,
        )

        with patch("app.api.dependencies.get_settings", return_value=settings):
            with self.assertRaises(HTTPException) as raised:
                get_actor_context(
                    authorization=None,
                    x_actor_id="local",
                    x_actor_roles="warehouse_manager",
                    x_actor_warehouse_ids=None,
                    x_actor_department=None,
                )

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail["code"], "unauthorized")

    def test_production_runtime_rejects_public_or_missing_auth_config(self) -> None:
        from app.core.config import Settings

        public_settings = Settings(
            deployment_mode="production",
            database_backend="postgresql",
            database_url="postgresql+psycopg://user:pass@db:5432/sklad",
            public_access_enabled=True,
            dev_auth_enabled=False,
            jwt_hmac_secret="secret",
        )
        self.assertEqual(
            public_settings.runtime_configuration_error(),
            "SKLAD_PUBLIC_ACCESS_ENABLED must be false in production",
        )

        missing_auth_settings = Settings(
            deployment_mode="production",
            database_backend="postgresql",
            database_url="postgresql+psycopg://user:pass@db:5432/sklad",
            public_access_enabled=False,
            dev_auth_enabled=False,
            jwt_hmac_secret=None,
            oidc_enabled=False,
        )
        self.assertEqual(
            missing_auth_settings.runtime_configuration_error(),
            "Production requires SKLAD_JWT_HMAC_SECRET or SKLAD_OIDC_ENABLED=true",
        )

    def test_production_mode_uses_bearer_token_for_actor_context(self) -> None:
        from app.api.dependencies import get_actor_context
        from app.core.config import Settings

        with patch.dict(__import__("os").environ, {
            "SKLAD_JWT_ISSUER": "",
            "SKLAD_JWT_AUDIENCE": "",
            "SKLAD_OIDC_ENABLED": "false",
        }, clear=False):
            Settings.model_config["env_file"] = None
            settings = Settings(
                public_access_enabled=False,
                dev_auth_enabled=False,
                jwt_hmac_secret="secret",
                jwt_issuer=None,
                jwt_audience=None,
                oidc_enabled=False,
            )
        token = encode_jwt_hs256(
            {"sub": "token-actor", "roles": ["head_nurse"], "warehouse_ids": [3]},
            "secret",
        )

        with patch("app.api.dependencies.get_settings", return_value=settings):
            actor = get_actor_context(
                authorization=f"Bearer {token}",
                x_actor_id="spoofed",
                x_actor_roles="warehouse_manager",
                x_actor_warehouse_ids=None,
                x_actor_department=None,
            )

        self.assertEqual(actor.actor_id, "token-actor")
        self.assertEqual(actor.roles, frozenset({Role.HEAD_NURSE}))
        self.assertEqual(actor.warehouse_ids, frozenset({3}))

    def test_dev_headers_work_only_when_dev_auth_is_enabled(self) -> None:
        from app.api.dependencies import get_actor_context
        from app.core.config import Settings

        settings = Settings(dev_auth_enabled=True, jwt_hmac_secret=None)

        with patch("app.api.dependencies.get_settings", return_value=settings):
            actor = get_actor_context(
                authorization=None,
                x_actor_id="local",
                x_actor_roles="warehouse_manager",
                x_actor_warehouse_ids=None,
                x_actor_department=None,
            )

        self.assertEqual(actor.actor_id, "local")
        self.assertEqual(actor.roles, frozenset({Role.WAREHOUSE_MANAGER}))

    def test_public_access_uses_default_manager_without_token(self) -> None:
        from app.api.dependencies import get_actor_context
        from app.core.config import Settings

        settings = Settings(public_access_enabled=True, dev_auth_enabled=False, jwt_hmac_secret=None)

        with patch("app.api.dependencies.get_settings", return_value=settings):
            actor = get_actor_context(
                authorization=None,
                x_actor_id="public",
                x_actor_roles=None,
                x_actor_warehouse_ids=None,
                x_actor_department=None,
            )

        self.assertEqual(actor.actor_id, "public")
        self.assertEqual(actor.roles, frozenset({Role.WAREHOUSE_MANAGER}))

    def test_public_access_ignores_invalid_bearer_token(self) -> None:
        from app.api.dependencies import get_actor_context
        from app.core.config import Settings

        settings = Settings(
            public_access_enabled=True,
            dev_auth_enabled=False,
            jwt_hmac_secret="secret",
        )

        with patch("app.api.dependencies.get_settings", return_value=settings):
            actor = get_actor_context(
                authorization="Bearer stale-browser-token",
                x_actor_id="public",
                x_actor_roles=None,
                x_actor_warehouse_ids=None,
                x_actor_department=None,
            )

        self.assertEqual(actor.actor_id, "public")
        self.assertEqual(actor.roles, frozenset({Role.WAREHOUSE_MANAGER}))
