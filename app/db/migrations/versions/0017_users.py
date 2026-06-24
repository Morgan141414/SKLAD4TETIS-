from __future__ import annotations

from alembic import op

revision = '0017_users'
down_revision = '0016_batch_serial_numbers'
branch_labels = None
depends_on = None

_ADMIN_HASH = '$2b$12$C05TWU8MCah3iucEzC.va.uld78x3CcEz0BUNdJ35IknhBz1.XFqu'


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sklad_users (
          id BIGSERIAL PRIMARY KEY,
          username TEXT NOT NULL,
          full_name TEXT NOT NULL,
          password_hash TEXT NOT NULL,
          roles TEXT NOT NULL DEFAULT 'warehouse_manager',
          warehouse_ids JSONB NOT NULL DEFAULT '[]',
          department TEXT,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sklad_users_username ON sklad_users(username)")
    op.execute(
        """
        INSERT INTO sklad_users (username, full_name, password_hash, roles, warehouse_ids)
        SELECT 'admin', 'Administrator', '{}', 'warehouse_manager', '[]'
        WHERE NOT EXISTS (SELECT 1 FROM sklad_users WHERE username = 'admin')
        """.format(_ADMIN_HASH)
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sklad_users")
