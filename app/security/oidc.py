import json
import logging
import threading
import time
from typing import Any

import httpx

from app.domain.errors import AuthenticationError
from app.security.rbac import ActorContext, Role

logger = logging.getLogger(__name__)


class JwksCache:
    """Thread-safe JWKS key cache with TTL refresh."""

    def __init__(self, jwks_uri: str, ttl_seconds: int = 300) -> None:
        self.jwks_uri = jwks_uri
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._loaded_at: float = 0.0

    def get_key(self, kid: str | None) -> Any:
        import jwt as pyjwt

        with self._lock:
            if time.monotonic() - self._loaded_at > self.ttl_seconds:
                self._refresh()
        if not self._keys:
            raise AuthenticationError("OIDC JWKS unavailable — no keys loaded")
        # If kid specified, match it; else fall back to first key
        if kid and kid in self._keys:
            raw = self._keys[kid]
        elif kid and kid not in self._keys:
            # Try refreshing once on unknown kid
            with self._lock:
                self._refresh()
            raw = self._keys.get(kid) or next(iter(self._keys.values()), None)
        else:
            raw = next(iter(self._keys.values()), None)
        if raw is None:
            raise AuthenticationError("OIDC JWKS: no matching key")
        return pyjwt.algorithms.RSAAlgorithm.from_jwk(raw)

    def _refresh(self) -> None:
        try:
            resp = httpx.get(self.jwks_uri, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            self._keys = {k["kid"]: k for k in data.get("keys", []) if "kid" in k}
            self._loaded_at = time.monotonic()
            logger.info("OIDC JWKS refreshed: %d keys from %s", len(self._keys), self.jwks_uri)
        except Exception:
            logger.exception("Failed to refresh OIDC JWKS from %s", self.jwks_uri)


_jwks_cache: JwksCache | None = None


def init_oidc(jwks_uri: str) -> None:
    global _jwks_cache
    _jwks_cache = JwksCache(jwks_uri)
    logger.info("OIDC initialized with JWKS URI: %s", jwks_uri)


def actor_from_oidc_token(
    token: str,
    *,
    audience: str | None = None,
    issuer: str | None = None,
    role_mapping: dict[str, str] | None = None,
    leeway_seconds: int = 30,
) -> ActorContext:
    """Validate an OIDC/Keycloak JWT (RS256) and return ActorContext."""
    if _jwks_cache is None:
        raise AuthenticationError("OIDC is not initialized")

    import jwt as pyjwt

    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.exceptions.DecodeError as e:
        raise AuthenticationError("Invalid bearer token") from e

    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    if alg not in ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512"):
        raise AuthenticationError(f"Unsupported OIDC JWT algorithm: {alg}")

    pub_key = _jwks_cache.get_key(kid)

    decode_kwargs: dict[str, Any] = {
        "algorithms": [alg],
        "leeway": leeway_seconds,
        "options": {"verify_exp": True},
    }
    if audience:
        decode_kwargs["audience"] = audience
    if issuer:
        decode_kwargs["issuer"] = issuer

    try:
        payload = pyjwt.decode(token, pub_key, **decode_kwargs)
    except pyjwt.exceptions.ExpiredSignatureError as e:
        raise AuthenticationError("Bearer token has expired") from e
    except pyjwt.exceptions.InvalidAudienceError as e:
        raise AuthenticationError("Invalid bearer token audience") from e
    except pyjwt.exceptions.InvalidIssuerError as e:
        raise AuthenticationError("Invalid bearer token issuer") from e
    except pyjwt.exceptions.PyJWTError as e:
        raise AuthenticationError("Invalid bearer token") from e

    return _actor_from_oidc_payload(payload, role_mapping=role_mapping or {})


def _actor_from_oidc_payload(
    payload: dict[str, Any],
    *,
    role_mapping: dict[str, str],
) -> ActorContext:
    actor_id = payload.get("sub") or payload.get("preferred_username")
    if not actor_id or not str(actor_id).strip():
        raise AuthenticationError("OIDC token missing subject")

    # Extract roles from Keycloak JWT: realm_access.roles or roles claim
    raw_roles: list[str] = []
    realm_access = payload.get("realm_access", {})
    if isinstance(realm_access, dict):
        raw_roles.extend(realm_access.get("roles", []))
    # Also check top-level roles claim (for custom mappers)
    top_roles = payload.get("roles", [])
    if isinstance(top_roles, list):
        raw_roles.extend(top_roles)
    elif isinstance(top_roles, str):
        raw_roles.extend(r.strip() for r in top_roles.split(",") if r.strip())

    # Apply mapping
    mapped_roles: set[Role] = set()
    for raw in raw_roles:
        mapped = role_mapping.get(raw, raw)
        try:
            mapped_roles.add(Role(mapped))
        except ValueError:
            pass  # Ignore unknown roles

    if not mapped_roles:
        raise AuthenticationError("OIDC token has no recognized sklad roles")

    # warehouse_ids: custom claim or empty (unrestricted)
    warehouse_ids: set[int] = set()
    wids = payload.get("warehouse_ids", [])
    if isinstance(wids, list):
        for w in wids:
            if isinstance(w, int):
                warehouse_ids.add(w)

    department = payload.get("department") or None

    return ActorContext(
        actor_id=str(actor_id),
        roles=frozenset(mapped_roles),
        warehouse_ids=frozenset(warehouse_ids),
        department=department,
    )
