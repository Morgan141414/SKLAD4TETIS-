from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.errors import AuthenticationError, PermissionDeniedError, ValidationError


class Permission(StrEnum):
    CATALOG_WRITE = "catalog:write"
    STOCK_READ = "stock:read"
    STOCK_RECEIVE = "stock:receive"
    STOCK_WRITEOFF = "stock:writeoff"
    STOCK_TRANSFER = "stock:transfer"
    STOCK_RESERVE = "stock:reserve"
    DOCUMENT_CREATE = "documents:create"
    DOCUMENT_POST = "documents:post"
    INVENTORY_MANAGE = "inventory:manage"
    NOTIFICATIONS_READ = "notifications:read"
    AUDIT_READ = "audit:read"
    ADMIN_USERS = "admin:users"
    SUPPLIER_PROFILE_READ = "supplier:profile:read"
    SUPPLIER_PROFILE_WRITE = "supplier:profile:write"
    SUPPLIER_ORDERS_READ = "supplier:orders:read"
    SUPPLIER_OFFERS_WRITE = "supplier:offers:write"


class Role(StrEnum):
    WAREHOUSE_MANAGER = "warehouse_manager"
    HEAD_NURSE = "head_nurse"
    NURSE = "nurse"
    DOCTOR = "doctor"
    OTHER = "other"
    SUPPLIER = "supplier"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.WAREHOUSE_MANAGER: frozenset(Permission),
    Role.HEAD_NURSE: frozenset(
        {
            Permission.STOCK_READ,
            Permission.STOCK_RECEIVE,
            Permission.STOCK_WRITEOFF,
            Permission.STOCK_TRANSFER,
            Permission.STOCK_RESERVE,
            Permission.DOCUMENT_CREATE,
            Permission.INVENTORY_MANAGE,
            Permission.NOTIFICATIONS_READ,
        }
    ),
    Role.NURSE: frozenset(
        {
            Permission.STOCK_READ,
            Permission.STOCK_WRITEOFF,
            Permission.NOTIFICATIONS_READ,
        }
    ),
    Role.DOCTOR: frozenset(
        {
            Permission.STOCK_READ,
            Permission.STOCK_RESERVE,
        }
    ),
    Role.OTHER: frozenset({Permission.STOCK_WRITEOFF}),
    Role.SUPPLIER: frozenset(
        {
            Permission.SUPPLIER_PROFILE_READ,
            Permission.SUPPLIER_PROFILE_WRITE,
            Permission.SUPPLIER_ORDERS_READ,
            Permission.SUPPLIER_OFFERS_WRITE,
        }
    ),
}


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    warehouse_ids: frozenset[int] = field(default_factory=frozenset)
    department: str | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        permissions: set[Permission] = set()
        for role in self.roles:
            permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
        return frozenset(permissions)


def has_permission(actor: ActorContext, permission: Permission) -> bool:
    return permission in actor.permissions


def require_permission(actor: ActorContext, permission: Permission) -> None:
    if not has_permission(actor, permission):
        raise PermissionDeniedError(f"Permission denied: {permission}")


def require_warehouse_scope(actor: ActorContext, warehouse_id: int) -> None:
    if Role.WAREHOUSE_MANAGER in actor.roles:
        return
    if warehouse_id not in actor.warehouse_ids:
        raise PermissionDeniedError(f"Warehouse scope denied: {warehouse_id}")


def require_warehouse_filter(actor: ActorContext, warehouse_id: int | None) -> None:
    if Role.WAREHOUSE_MANAGER in actor.roles:
        return
    if warehouse_id is None:
        raise PermissionDeniedError("Warehouse filter is required for scoped actor")
    require_warehouse_scope(actor, warehouse_id)


def require_stock_access(
    actor: ActorContext, permission: Permission, warehouse_id: int | None = None
) -> None:
    require_permission(actor, permission)
    if warehouse_id is not None:
        require_warehouse_scope(actor, warehouse_id)


def dev_actor(actor_id: str = "system") -> ActorContext:
    return ActorContext(actor_id=actor_id, roles=frozenset({Role.WAREHOUSE_MANAGER}))


def actor_from_headers(
    actor_id: str = "system",
    roles_header: str | None = None,
    warehouse_ids_header: str | None = None,
    department: str | None = None,
    allow_dev_default: bool = False,
) -> ActorContext:
    if not roles_header:
        if not allow_dev_default:
            raise AuthenticationError("Authentication credentials are required")
        return dev_actor(actor_id)

    roles: set[Role] = set()
    for raw_role in roles_header.split(","):
        role = raw_role.strip()
        if not role:
            continue
        try:
            roles.add(Role(role))
        except ValueError as error:
            raise ValidationError(f"Unknown role: {role}") from error

    warehouse_ids: set[int] = set()
    if warehouse_ids_header:
        for raw_warehouse_id in warehouse_ids_header.split(","):
            warehouse_id = raw_warehouse_id.strip()
            if not warehouse_id:
                continue
            try:
                warehouse_ids.add(int(warehouse_id))
            except ValueError as error:
                raise ValidationError(f"Invalid warehouse id: {warehouse_id}") from error

    return ActorContext(
        actor_id=actor_id,
        roles=frozenset(roles),
        warehouse_ids=frozenset(warehouse_ids),
        department=department,
    )
