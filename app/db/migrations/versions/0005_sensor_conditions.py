"""add storage condition sensor journal

Revision ID: 0005_sensor_conditions
Revises: 0004_quarantine_reviews
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op


revision = "0005_sensor_conditions"
down_revision = "0004_quarantine_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_devices (
          id BIGSERIAL PRIMARY KEY,
          warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
          name TEXT NOT NULL,
          serial_number TEXT,
          sensor_type TEXT NOT NULL DEFAULT 'temperature_humidity',
          min_temperature_c NUMERIC(8, 3),
          max_temperature_c NUMERIC(8, 3),
          min_humidity_percent NUMERIC(8, 3),
          max_humidity_percent NUMERIC(8, 3),
          created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL,
          CONSTRAINT sensor_devices_temperature_range_check CHECK (
            min_temperature_c IS NULL OR max_temperature_c IS NULL
            OR min_temperature_c <= max_temperature_c
          ),
          CONSTRAINT sensor_devices_humidity_range_check CHECK (
            min_humidity_percent IS NULL OR max_humidity_percent IS NULL
            OR min_humidity_percent <= max_humidity_percent
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sensor_devices_warehouse
          ON sensor_devices(warehouse_id, id)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_readings (
          id BIGSERIAL PRIMARY KEY,
          device_id BIGINT NOT NULL REFERENCES sensor_devices(id),
          warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
          temperature_c NUMERIC(8, 3),
          humidity_percent NUMERIC(8, 3),
          recorded_at TIMESTAMPTZ NOT NULL,
          received_at TIMESTAMPTZ NOT NULL,
          status TEXT NOT NULL,
          raw_payload TEXT,
          CONSTRAINT sensor_readings_has_value_check CHECK (
            temperature_c IS NOT NULL OR humidity_percent IS NOT NULL
          ),
          CONSTRAINT sensor_readings_humidity_range_check CHECK (
            humidity_percent IS NULL OR (humidity_percent >= 0 AND humidity_percent <= 100)
          ),
          CONSTRAINT sensor_readings_status_check CHECK (status IN ('ok', 'warning'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_warehouse_recorded
          ON sensor_readings(warehouse_id, recorded_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_device_recorded
          ON sensor_readings(device_id, recorded_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sensor_readings_device_recorded")
    op.execute("DROP INDEX IF EXISTS idx_sensor_readings_warehouse_recorded")
    op.execute("DROP TABLE IF EXISTS sensor_readings")
    op.execute("DROP INDEX IF EXISTS idx_sensor_devices_warehouse")
    op.execute("DROP TABLE IF EXISTS sensor_devices")
