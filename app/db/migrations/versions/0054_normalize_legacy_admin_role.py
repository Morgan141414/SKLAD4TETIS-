"""Normalize the historical admin role to warehouse_manager.

Revision ID: 0054_normalize_legacy_admin_role
Revises: 0053_marketplace_buy_requests
"""

from alembic import op


revision = "0054_normalize_legacy_admin_role"
down_revision = "0053_marketplace_buy_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # roles is a comma-separated legacy column. Work token-by-token so values
    # such as "domain_admin" are never modified accidentally.
    op.execute(
        """
        UPDATE sklad_users
           SET roles = array_to_string(
               ARRAY(
                   SELECT CASE WHEN trim(role_name) = 'admin'
                               THEN 'warehouse_manager'
                               ELSE trim(role_name)
                          END
                     FROM unnest(string_to_array(roles, ',')) AS role_name
               ),
               ','
           )
         WHERE 'admin' = ANY(
             ARRAY(SELECT trim(role_name)
                     FROM unnest(string_to_array(roles, ',')) AS role_name)
         )
        """
    )


def downgrade() -> None:
    # Deliberately irreversible: warehouse_manager is the canonical role and
    # may have existed before this migration, so converting it back is unsafe.
    pass
