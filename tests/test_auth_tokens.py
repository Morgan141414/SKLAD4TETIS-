import time
from unittest import TestCase

from app.domain.errors import AuthenticationError, ValidationError
from app.security.rbac import Role
from app.security.tokens import actor_from_bearer_token, decode_jwt_hs256, encode_jwt_hs256


class AuthTokenTest(TestCase):
    def test_bearer_token_builds_actor_context(self) -> None:
        token = encode_jwt_hs256(
            {
                "sub": "nurse-1",
                "roles": ["nurse", "doctor"],
                "warehouse_ids": [10, 20],
                "department": "therapy",
                "exp": int(time.time()) + 60,
            },
            "secret",
        )

        actor = actor_from_bearer_token(token, secret="secret")

        self.assertEqual(actor.actor_id, "nurse-1")
        self.assertEqual(actor.roles, frozenset({Role.NURSE, Role.DOCTOR}))
        self.assertEqual(actor.warehouse_ids, frozenset({10, 20}))
        self.assertEqual(actor.department, "therapy")

    def test_tampered_token_is_rejected(self) -> None:
        token = encode_jwt_hs256(
            {"sub": "nurse-1", "roles": ["nurse"], "warehouse_ids": [10]},
            "secret",
        )
        header, payload, _signature = token.split(".")
        tampered = f"{header}.{payload}.invalid"

        with self.assertRaises(AuthenticationError):
            decode_jwt_hs256(tampered, secret="secret")

    def test_expired_token_is_rejected(self) -> None:
        token = encode_jwt_hs256(
            {"sub": "nurse-1", "roles": ["nurse"], "exp": 100},
            "secret",
        )

        with self.assertRaises(AuthenticationError):
            decode_jwt_hs256(token, secret="secret", now=200, leeway_seconds=0)

    def test_issuer_and_audience_are_validated_when_configured(self) -> None:
        token = encode_jwt_hs256(
            {
                "sub": "nurse-1",
                "roles": ["nurse"],
                "iss": "sklad",
                "aud": ["api", "mobile"],
            },
            "secret",
        )

        payload = decode_jwt_hs256(token, secret="secret", issuer="sklad", audience="api")

        self.assertEqual(payload["sub"], "nurse-1")
        with self.assertRaises(AuthenticationError):
            decode_jwt_hs256(token, secret="secret", issuer="other", audience="api")
        with self.assertRaises(AuthenticationError):
            decode_jwt_hs256(token, secret="secret", issuer="sklad", audience="web")

    def test_unknown_role_is_validation_error(self) -> None:
        token = encode_jwt_hs256(
            {"sub": "nurse-1", "roles": ["superuser"]},
            "secret",
        )

        with self.assertRaises(ValidationError):
            actor_from_bearer_token(token, secret="secret")
