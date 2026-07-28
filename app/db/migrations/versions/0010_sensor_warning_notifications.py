"""add sensor warning notification links

Revision ID: 0010_sensor_warning_notifications
Revises: 0009_controlled_writeoff_second_confirmation
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0010_sensor_warning_notifications"
down_revision = "0009_controlled_writeoff_second_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS device_id BIGINT REFERENCES sensor_devices(id)")
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS sensor_reading_id BIGINT REFERENCES sensor_readings(id)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_unread_sensor_warning_device
          ON notifications(device_id)
          WHERE notification_type = 'sensor_warning' AND is_read = FALSE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_notifications_unread_sensor_warning_device")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS sensor_reading_id")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS device_id")
