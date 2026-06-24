from pathlib import Path

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.domain.errors import AuthenticationError, ValidationError
from app.repositories.idempotency import PostgresIdempotencyRepository, SQLiteIdempotencyRepository
from app.services.idempotency import IdempotencyStore
from app.services.warehouse import WarehouseService
from app.security.rbac import ActorContext, actor_from_headers
from app.security.tokens import actor_from_bearer_token
from app.security.oidc import actor_from_oidc_token
from app.storage.base import WarehouseDatabase
from app.storage.postgresql import PostgresDatabase
from app.storage.sqlite import SQLiteDatabase


_database: WarehouseDatabase | None = None
POSTGRESQL_REQUIRED_REVISION = "0001_initial_postgresql"
POSTGRESQL_MIGRATION_COMMAND = "alembic upgrade head"
POSTGRESQL_RUNTIME_ADAPTER_DETAIL = "PostgreSQL runtime adapter is enabled"


def _postgresql_runtime_error_detail() -> str:
    return (
        f"Apply PostgreSQL migrations through {POSTGRESQL_REQUIRED_REVISION} with "
        f"`{POSTGRESQL_MIGRATION_COMMAND}` before enabling PostgreSQL runtime."
    )


def get_database() -> WarehouseDatabase:
    global _database
    if _database is None:
        settings = get_settings()
        configuration_error = settings.runtime_configuration_error()
        if configuration_error:
            raise RuntimeError(configuration_error)
        if settings.database_backend == "postgresql":
            _database = PostgresDatabase(settings.database_url)
            return _database
        _database = SQLiteDatabase(Path(settings.sqlite_path))
        _database.init_schema()
    return _database


def get_database_readiness() -> dict[str, str]:
    settings = get_settings()
    configuration_error = settings.runtime_configuration_error()
    if configuration_error:
        return {
            "status": "error",
            "backend": settings.database_backend,
            "mode": settings.deployment_mode,
            "detail": configuration_error,
        }
    try:
        database = get_database()
        connection = database.connect()
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            if not isinstance(database, SQLiteDatabase) or database.path != ":memory:":
                connection.close()
    except Exception as error:
        return {"status": "error", "backend": settings.database_backend, "detail": str(error)}
    detail = "ready" if settings.database_backend == "sqlite" else POSTGRESQL_RUNTIME_ADAPTER_DETAIL
    return {
        "status": "ok",
        "backend": settings.database_backend,
        "mode": settings.deployment_mode,
        "detail": detail,
    }


def get_warehouse_service() -> WarehouseService:
    return WarehouseService(get_database())


def get_idempotency_store() -> IdempotencyStore:
    settings = get_settings()
    if settings.database_backend == "postgresql":
        return IdempotencyStore(PostgresIdempotencyRepository())
    database = get_database()
    if not isinstance(database, SQLiteDatabase):
        raise RuntimeError("SQLite idempotency repository requires SQLiteDatabase")
    return IdempotencyStore(SQLiteIdempotencyRepository(database))


def get_actor_context(
    authorization: str | None = Header(default=None),
    x_actor_id: str = Header(default="system"),
    x_actor_roles: str | None = Header(default=None),
    x_actor_warehouse_ids: str | None = Header(default=None),
    x_actor_department: str | None = Header(default=None),
) -> ActorContext:
    settings = get_settings()
    if settings.public_access_enabled:
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                # Try OIDC first if enabled
                if settings.oidc_enabled:
                    try:
                        import json as _json
                        role_map = _json.loads(settings.oidc_role_mapping_json) if settings.oidc_role_mapping_json else {}
                        return actor_from_oidc_token(
                            token.strip(),
                            audience=settings.oidc_audience,
                            issuer=settings.oidc_issuer,
                            role_mapping=role_map,
                            leeway_seconds=settings.jwt_clock_skew_seconds,
                        )
                    except (AuthenticationError, ValidationError):
                        pass
                # Fall back to HS256
                if settings.jwt_hmac_secret:
                    try:
                        return actor_from_bearer_token(
                            token.strip(),
                            secret=settings.jwt_hmac_secret,
                            issuer=settings.jwt_issuer,
                            audience=settings.jwt_audience,
                            leeway_seconds=settings.jwt_clock_skew_seconds,
                        )
                    except (AuthenticationError, ValidationError):
                        pass
        try:
            return actor_from_headers(
                actor_id=x_actor_id or "public-user",
                roles_header=x_actor_roles,
                warehouse_ids_header=x_actor_warehouse_ids,
                department=x_actor_department,
                allow_dev_default=True,
            )
        except AuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": str(error), "details": {}},
            ) from error
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": str(error), "details": {}},
            ) from error
    if not settings.dev_auth_enabled:
        if not authorization:
            raise _unauthorized("Authentication credentials are required")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise _unauthorized("Bearer token is required")
        if not settings.jwt_hmac_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "server_error",
                    "message": "JWT HMAC secret is not configured",
                    "details": {},
                },
            )
        if settings.oidc_enabled:
            try:
                import json as _json
                role_map = _json.loads(settings.oidc_role_mapping_json) if settings.oidc_role_mapping_json else {}
                return actor_from_oidc_token(
                    token.strip(),
                    audience=settings.oidc_audience,
                    issuer=settings.oidc_issuer,
                    role_mapping=role_map,
                    leeway_seconds=settings.jwt_clock_skew_seconds,
                )
            except (AuthenticationError, ValidationError) as error:
                if not settings.jwt_hmac_secret:
                    raise _unauthorized(str(error)) from error
        try:
            return actor_from_bearer_token(
                token.strip(),
                secret=settings.jwt_hmac_secret,
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                leeway_seconds=settings.jwt_clock_skew_seconds,
            )
        except AuthenticationError as error:
            raise _unauthorized(str(error)) from error
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "validation_error", "message": str(error), "details": {}},
            ) from error
    try:
        return actor_from_headers(
            actor_id=x_actor_id,
            roles_header=x_actor_roles,
            warehouse_ids_header=x_actor_warehouse_ids,
            department=x_actor_department,
            allow_dev_default=settings.dev_auth_enabled,
        )
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": str(error), "details": {}},
        ) from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": str(error), "details": {}},
        ) from error


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": message, "details": {}},
        headers={"WWW-Authenticate": "Bearer"},
    )
