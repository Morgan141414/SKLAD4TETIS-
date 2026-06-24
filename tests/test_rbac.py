from unittest import TestCase

from app.domain.errors import AuthenticationError, ValidationError
from app.security.rbac import (
    ActorContext,
    Permission,
    Role,
    actor_from_headers,
    dev_actor,
    has_permission,
    require_permission_or_supplier,
    require_stock_access,
    require_supplier_scope,
    require_warehouse_filter,
    require_warehouse_scope,
)


class RBACTest(TestCase):
    def test_warehouse_manager_has_all_permissions_and_global_scope(self) -> None:
        actor = ActorContext(actor_id="manager", roles=frozenset({Role.WAREHOUSE_MANAGER}))

        self.assertTrue(has_permission(actor, Permission.AUDIT_READ))
        require_warehouse_scope(actor, warehouse_id=999)

    def test_nurse_cannot_manage_inventory(self) -> None:
        actor = ActorContext(
            actor_id="nurse",
            roles=frozenset({Role.NURSE}),
            warehouse_ids=frozenset({10}),
        )

        self.assertTrue(has_permission(actor, Permission.STOCK_WRITEOFF))
        self.assertFalse(has_permission(actor, Permission.INVENTORY_MANAGE))

        with self.assertRaises(ValidationError):
            require_stock_access(actor, Permission.INVENTORY_MANAGE, warehouse_id=10)

    def test_scope_denies_unassigned_warehouse(self) -> None:
        actor = ActorContext(
            actor_id="head-nurse",
            roles=frozenset({Role.HEAD_NURSE}),
            warehouse_ids=frozenset({1, 2}),
        )

        require_stock_access(actor, Permission.STOCK_TRANSFER, warehouse_id=1)
        with self.assertRaises(ValidationError):
            require_stock_access(actor, Permission.STOCK_TRANSFER, warehouse_id=3)

    def test_dev_actor_is_manager_compatible(self) -> None:
        actor = dev_actor("local-test")

        self.assertEqual(actor.actor_id, "local-test")
        self.assertTrue(has_permission(actor, Permission.ADMIN_USERS))

    def test_actor_context_can_be_built_from_headers(self) -> None:
        actor = actor_from_headers(
            actor_id="nurse-1",
            roles_header="nurse,doctor",
            warehouse_ids_header="10, 20",
            department="therapy",
        )

        self.assertEqual(actor.actor_id, "nurse-1")
        self.assertEqual(actor.roles, frozenset({Role.NURSE, Role.DOCTOR}))
        self.assertEqual(actor.warehouse_ids, frozenset({10, 20}))
        self.assertEqual(actor.department, "therapy")

    def test_actor_without_role_header_requires_authentication_by_default(self) -> None:
        with self.assertRaises(AuthenticationError):
            actor_from_headers(actor_id="system")

    def test_dev_actor_context_can_default_to_manager_when_explicitly_allowed(self) -> None:
        actor = actor_from_headers(actor_id="system", allow_dev_default=True)

        self.assertEqual(actor.roles, frozenset({Role.WAREHOUSE_MANAGER}))

    def test_scoped_actor_must_filter_global_reads_by_warehouse(self) -> None:
        actor = ActorContext(
            actor_id="nurse",
            roles=frozenset({Role.NURSE}),
            warehouse_ids=frozenset({10}),
        )

        require_warehouse_filter(actor, warehouse_id=10)
        with self.assertRaises(ValidationError):
            require_warehouse_filter(actor, warehouse_id=None)

    def test_supplier_role_has_only_portal_permission(self) -> None:
        actor = ActorContext(actor_id="supplier:7", roles=frozenset({Role.SUPPLIER}), supplier_id=7)

        self.assertTrue(has_permission(actor, Permission.SUPPLIER_PORTAL))
        self.assertFalse(has_permission(actor, Permission.STOCK_READ))
        self.assertFalse(has_permission(actor, Permission.ADMIN_USERS))

    def test_supplier_scope_is_locked_to_own_id(self) -> None:
        actor = ActorContext(actor_id="supplier:7", roles=frozenset({Role.SUPPLIER}), supplier_id=7)

        require_supplier_scope(actor, 7)
        with self.assertRaises(ValidationError):
            require_supplier_scope(actor, 8)

    def test_staff_is_unrestricted_by_supplier_scope(self) -> None:
        manager = ActorContext(actor_id="manager", roles=frozenset({Role.WAREHOUSE_MANAGER}))

        require_supplier_scope(manager, 1)
        require_supplier_scope(manager, 999)

    def test_require_permission_or_supplier_admits_supplier_without_staff_permission(self) -> None:
        actor = ActorContext(actor_id="supplier:7", roles=frozenset({Role.SUPPLIER}), supplier_id=7)

        require_permission_or_supplier(actor, Permission.STOCK_READ)
        require_permission_or_supplier(actor, Permission.STOCK_RECEIVE)

    def test_require_permission_or_supplier_still_enforces_staff_permissions(self) -> None:
        nurse = ActorContext(actor_id="nurse", roles=frozenset({Role.NURSE}), warehouse_ids=frozenset({1}))

        with self.assertRaises(ValidationError):
            require_permission_or_supplier(nurse, Permission.ADMIN_USERS)
