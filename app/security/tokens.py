import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any

from app.domain.errors import AuthenticationError, ValidationError
from app.security.rbac import ActorContext, Role


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as error:
        raise AuthenticationError("Invalid bearer token") from error


def _json_object(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AuthenticationError("Invalid bearer token") from error
    if not isinstance(value, dict):
        raise AuthenticationError("Invalid bearer token")
    return value


def encode_jwt_hs256(payload: dict[str, Any], secret: str) -> str:
    if not secret:
        raise ValueError("JWT HMAC secret is required")

    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        (
            _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        )
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_jwt_hs256(
    token: str,
    *,
    secret: str,
    issuer: str | None = None,
    audience: str | None = None,
    leeway_seconds: int = 30,
    now: int | None = None,
) -> dict[str, Any]:
    if not secret:
        raise AuthenticationError("JWT HMAC secret is not configured")

    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise AuthenticationError("Invalid bearer token")

    header = _json_object(_b64url_decode(parts[0]))
    if header.get("alg") != "HS256":
        raise AuthenticationError("Invalid bearer token")

    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    supplied = _b64url_decode(parts[2])
    if not hmac.compare_digest(expected, supplied):
        raise AuthenticationError("Invalid bearer token")

    payload = _json_object(_b64url_decode(parts[1]))
    timestamp = int(time.time()) if now is None else now
    leeway = max(0, leeway_seconds)

    exp = payload.get("exp")
    if exp is not None and _numeric_claim(exp, "exp") < timestamp - leeway:
        raise AuthenticationError("Bearer token has expired")

    nbf = payload.get("nbf")
    if nbf is not None and _numeric_claim(nbf, "nbf") > timestamp + leeway:
        raise AuthenticationError("Bearer token is not active yet")

    iat = payload.get("iat")
    if iat is not None and _numeric_claim(iat, "iat") > timestamp + leeway:
        raise AuthenticationError("Bearer token is not active yet")

    if issuer is not None and payload.get("iss") != issuer:
        raise AuthenticationError("Invalid bearer token issuer")

    if audience is not None and not _audience_matches(payload.get("aud"), audience):
        raise AuthenticationError("Invalid bearer token audience")

    return payload


def actor_from_jwt_claims(payload: dict[str, Any]) -> ActorContext:
    actor_id = payload.get("sub")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise AuthenticationError("Bearer token subject is required")

    roles = _roles_from_claim(payload.get("roles"))
    if not roles:
        raise AuthenticationError("Bearer token roles are required")

    warehouse_ids = _warehouse_ids_from_claim(payload.get("warehouse_ids"))
    department = payload.get("department")
    if department is not None and not isinstance(department, str):
        raise ValidationError("Invalid department")

    supplier_id = payload.get("supplier_id")
    if supplier_id is not None:
        supplier_id = _numeric_claim(supplier_id, "supplier_id")

    return ActorContext(
        actor_id=actor_id,
        roles=frozenset(roles),
        warehouse_ids=frozenset(warehouse_ids),
        department=department,
        supplier_id=supplier_id,
    )


def actor_from_bearer_token(
    token: str,
    *,
    secret: str,
    issuer: str | None = None,
    audience: str | None = None,
    leeway_seconds: int = 30,
) -> ActorContext:
    return actor_from_jwt_claims(
        decode_jwt_hs256(
            token,
            secret=secret,
            issuer=issuer,
            audience=audience,
            leeway_seconds=leeway_seconds,
        )
    )


def _numeric_claim(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuthenticationError(f"Invalid bearer token {name} claim")
    return int(value)


def _audience_matches(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return expected in value
    return False


def _roles_from_claim(value: Any) -> set[Role]:
    if isinstance(value, str):
        raw_roles = [role.strip() for role in value.split(",")]
    elif isinstance(value, list):
        raw_roles = value
    else:
        raise AuthenticationError("Bearer token roles are required")

    roles: set[Role] = set()
    for raw_role in raw_roles:
        if not isinstance(raw_role, str):
            raise ValidationError("Invalid role")
        role = raw_role.strip()
        if not role:
            continue
        try:
            roles.add(Role(role))
        except ValueError as error:
            raise ValidationError(f"Unknown role: {role}") from error
    return roles


def _warehouse_ids_from_claim(value: Any) -> set[int]:
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ValidationError("Invalid warehouse ids")

    warehouse_ids: set[int] = set()
    for raw_warehouse_id in value:
        if isinstance(raw_warehouse_id, bool) or not isinstance(raw_warehouse_id, int):
            raise ValidationError(f"Invalid warehouse id: {raw_warehouse_id}")
        warehouse_ids.add(raw_warehouse_id)
    return warehouse_ids
