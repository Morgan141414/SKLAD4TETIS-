CREATE TABLE IF NOT EXISTS categories (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS suppliers (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  bin TEXT,
  phone TEXT,
  address TEXT,
  rating INTEGER,
  is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
  contact_person TEXT,
  email TEXT,
  contract_number TEXT,
  contract_expires_on DATE,
  payment_terms TEXT,
  notes TEXT,
  CONSTRAINT suppliers_rating_range CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5))
);

CREATE TABLE IF NOT EXISTS warehouses (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  department TEXT,
  inventory_lock BOOLEAN NOT NULL DEFAULT FALSE,
  tetis_org_id TEXT,
  external_tetis_id TEXT,
  storage_zone TEXT,
  capacity_limit NUMERIC,
  storage_conditions TEXT,
  responsible_person TEXT
);

CREATE INDEX IF NOT EXISTS idx_warehouses_tetis_org_id
  ON warehouses(tetis_org_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_warehouses_tetis_org_external
  ON warehouses(tetis_org_id, external_tetis_id)
  WHERE tetis_org_id IS NOT NULL AND external_tetis_id IS NOT NULL;

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
    min_temperature_c IS NULL OR max_temperature_c IS NULL OR min_temperature_c <= max_temperature_c
  ),
  CONSTRAINT sensor_devices_humidity_range_check CHECK (
    min_humidity_percent IS NULL OR max_humidity_percent IS NULL
    OR min_humidity_percent <= max_humidity_percent
  )
);

CREATE INDEX IF NOT EXISTS idx_sensor_devices_warehouse
  ON sensor_devices(warehouse_id, id);

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
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_warehouse_recorded
  ON sensor_readings(warehouse_id, recorded_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_device_recorded
  ON sensor_readings(device_id, recorded_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS products (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  sku TEXT NOT NULL UNIQUE,
  unit TEXT NOT NULL,
  category_id BIGINT NOT NULL REFERENCES categories(id),
  reorder_point NUMERIC(18, 3) NOT NULL DEFAULT 0,
  safety_stock NUMERIC(18, 3) NOT NULL DEFAULT 0,
  is_controlled BOOLEAN NOT NULL DEFAULT FALSE,
  barcode TEXT,
  description TEXT,
  certificate_ref TEXT,
  CONSTRAINT products_reorder_point_non_negative CHECK (reorder_point >= 0),
  CONSTRAINT products_safety_stock_non_negative CHECK (safety_stock >= 0)
);

CREATE TABLE IF NOT EXISTS batches (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT NOT NULL REFERENCES products(id),
  supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
  received_at TIMESTAMPTZ NOT NULL,
  lot TEXT NOT NULL,
  serial_number TEXT,
  expires_on DATE,
  unit_price NUMERIC(18, 4) NOT NULL,
  status TEXT NOT NULL,
  CONSTRAINT batches_status_check CHECK (status IN ('available', 'quarantine', 'blocked')),
  CONSTRAINT batches_unit_price_non_negative CHECK (unit_price >= 0),
  UNIQUE(product_id, supplier_id, received_at, lot)
);

CREATE INDEX IF NOT EXISTS idx_batches_product_status_expiry
  ON batches(product_id, status, expires_on);

CREATE TABLE IF NOT EXISTS quarantine_reviews (
  id BIGSERIAL PRIMARY KEY,
  batch_id BIGINT NOT NULL REFERENCES batches(id),
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  status TEXT NOT NULL,
  responsible_id TEXT,
  due_at TIMESTAMPTZ,
  decision_reason TEXT,
  created_by TEXT NOT NULL,
  decided_by TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  decided_at TIMESTAMPTZ,
  CONSTRAINT quarantine_reviews_status_check CHECK (
    status IN ('pending', 'in_review', 'approved', 'rejected')
  ),
  UNIQUE(batch_id, warehouse_id)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_reviews_warehouse_status_due
  ON quarantine_reviews(warehouse_id, status, due_at, id);

CREATE TABLE IF NOT EXISTS batch_recalls (
  id BIGSERIAL PRIMARY KEY,
  batch_id BIGINT NOT NULL REFERENCES batches(id),
  product_id BIGINT NOT NULL REFERENCES products(id),
  reason TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  reference TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_recalls_batch_created
  ON batch_recalls(batch_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_batch_recalls_created
  ON batch_recalls(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS stock_balances (
  batch_id BIGINT NOT NULL REFERENCES batches(id),
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  quantity NUMERIC(18, 3) NOT NULL,
  reserved_quantity NUMERIC(18, 3) NOT NULL DEFAULT 0,
  PRIMARY KEY(batch_id, warehouse_id),
  CONSTRAINT stock_balances_quantity_non_negative CHECK (quantity >= 0),
  CONSTRAINT stock_balances_reserved_non_negative CHECK (reserved_quantity >= 0),
  CONSTRAINT stock_balances_reserved_lte_quantity CHECK (reserved_quantity <= quantity)
);

CREATE INDEX IF NOT EXISTS idx_stock_balances_warehouse
  ON stock_balances(warehouse_id);

CREATE TABLE IF NOT EXISTS stock_movements (
  id BIGSERIAL PRIMARY KEY,
  movement_type TEXT NOT NULL,
  batch_id BIGINT NOT NULL REFERENCES batches(id),
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  quantity NUMERIC(18, 3) NOT NULL,
  reason TEXT,
  patient_id TEXT,
  doctor_id TEXT,
  medical_record_no TEXT,
  second_approver_id TEXT,
  second_approval_note TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT stock_movements_type_check CHECK (
    movement_type IN (
      'receipt',
      'write_off',
      'reserve',
      'release_reserve',
      'transfer_out',
      'transfer_in',
      'return_to_supplier',
      'repack_out',
      'repack_in'
    )
  ),
  CONSTRAINT stock_movements_quantity_positive CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_stock_movements_batch_warehouse_created
  ON stock_movements(batch_id, warehouse_id, created_at DESC);

CREATE TABLE IF NOT EXISTS stock_documents (
  id BIGSERIAL PRIMARY KEY,
  document_type TEXT NOT NULL,
  status TEXT NOT NULL,
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  supplier_id BIGINT REFERENCES suppliers(id),
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,
  CONSTRAINT stock_documents_type_check CHECK (
    document_type IN (
      'receipt',
      'write_off',
      'transfer',
      'department_return',
      'supplier_return',
      'repack'
    )
  ),
  CONSTRAINT stock_documents_status_check CHECK (status IN ('draft', 'approved', 'posted', 'cancelled')),
  CONSTRAINT stock_documents_supplier_matches_type CHECK (
    (document_type IN ('receipt', 'supplier_return') AND supplier_id IS NOT NULL)
    OR (document_type IN ('write_off', 'transfer', 'department_return', 'repack') AND supplier_id IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_stock_documents_type_status_created
  ON stock_documents(document_type, status, created_at DESC);

CREATE TABLE IF NOT EXISTS stock_document_lines (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES stock_documents(id) ON DELETE CASCADE,
  product_id BIGINT REFERENCES products(id),
  batch_id BIGINT REFERENCES batches(id),
  target_warehouse_id BIGINT REFERENCES warehouses(id),
  target_product_id BIGINT REFERENCES products(id),
  quantity NUMERIC(18, 3) NOT NULL,
  target_quantity NUMERIC(18, 3),
  conversion_factor NUMERIC(18, 6),
  loss_quantity NUMERIC(18, 3),
  unit_price NUMERIC(18, 4),
  target_unit_price NUMERIC(18, 4),
  lot TEXT,
  serial_number TEXT,
  target_lot TEXT,
  expires_on DATE,
  target_expires_on DATE,
  quarantine BOOLEAN NOT NULL DEFAULT FALSE,
  reason TEXT,
  patient_id TEXT,
  doctor_id TEXT,
  medical_record_no TEXT,
  second_approver_id TEXT,
  second_approval_note TEXT,
  CONSTRAINT stock_document_lines_quantity_positive CHECK (quantity > 0),
  CONSTRAINT stock_document_lines_unit_price_non_negative CHECK (unit_price IS NULL OR unit_price >= 0),
  CONSTRAINT stock_document_lines_receipt_fields CHECK (
    (product_id IS NULL OR (unit_price IS NOT NULL AND lot IS NOT NULL))
  ),
  CONSTRAINT stock_document_lines_writeoff_fields CHECK (
    (batch_id IS NULL OR reason IS NOT NULL)
  ),
  CONSTRAINT stock_document_lines_repack_numbers CHECK (
    target_quantity IS NULL OR (target_quantity > 0 AND conversion_factor > 0 AND loss_quantity >= 0)
  )
);

CREATE INDEX IF NOT EXISTS idx_stock_document_lines_document_id
  ON stock_document_lines(document_id, id);

CREATE TABLE IF NOT EXISTS batch_transformations (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT REFERENCES stock_documents(id),
  source_batch_id BIGINT NOT NULL REFERENCES batches(id),
  target_batch_id BIGINT NOT NULL REFERENCES batches(id),
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  source_product_id BIGINT NOT NULL REFERENCES products(id),
  target_product_id BIGINT NOT NULL REFERENCES products(id),
  source_quantity NUMERIC(18, 3) NOT NULL,
  target_quantity NUMERIC(18, 3) NOT NULL,
  conversion_factor NUMERIC(18, 6) NOT NULL,
  loss_quantity NUMERIC(18, 3) NOT NULL DEFAULT 0,
  reason TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT batch_transformations_source_quantity_positive CHECK (source_quantity > 0),
  CONSTRAINT batch_transformations_target_quantity_positive CHECK (target_quantity > 0),
  CONSTRAINT batch_transformations_conversion_positive CHECK (conversion_factor > 0),
  CONSTRAINT batch_transformations_loss_non_negative CHECK (loss_quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_batch_transformations_source_batch
  ON batch_transformations(source_batch_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_batch_transformations_target_batch
  ON batch_transformations(target_batch_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_batch_transformations_document
  ON batch_transformations(document_id);

CREATE INDEX IF NOT EXISTS idx_batch_transformations_warehouse_created
  ON batch_transformations(warehouse_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS reservations (
  id BIGSERIAL PRIMARY KEY,
  batch_id BIGINT NOT NULL REFERENCES batches(id),
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  quantity NUMERIC(18, 3) NOT NULL,
  reserved_for TEXT NOT NULL,
  status TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT reservations_status_check CHECK (status IN ('reserved', 'used', 'released')),
  CONSTRAINT reservations_quantity_positive CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_reservations_status_expires
  ON reservations(status, expires_at);

CREATE TABLE IF NOT EXISTS inventory_sessions (
  id BIGSERIAL PRIMARY KEY,
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  status TEXT NOT NULL,
  started_by TEXT NOT NULL,
  posted_by TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  posted_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  CONSTRAINT inventory_sessions_status_check CHECK (status IN ('draft', 'in_progress', 'posted', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_inventory_sessions_warehouse_status
  ON inventory_sessions(warehouse_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_sessions_one_active
  ON inventory_sessions(warehouse_id)
  WHERE status = 'in_progress';

CREATE TABLE IF NOT EXISTS inventory_lines (
  id BIGSERIAL PRIMARY KEY,
  session_id BIGINT NOT NULL REFERENCES inventory_sessions(id) ON DELETE CASCADE,
  product_id BIGINT NOT NULL REFERENCES products(id),
  batch_id BIGINT NOT NULL REFERENCES batches(id),
  expected_quantity NUMERIC(18, 3) NOT NULL,
  actual_quantity NUMERIC(18, 3),
  difference_quantity NUMERIC(18, 3),
  UNIQUE(session_id, batch_id),
  CONSTRAINT inventory_lines_expected_non_negative CHECK (expected_quantity >= 0),
  CONSTRAINT inventory_lines_actual_non_negative CHECK (actual_quantity IS NULL OR actual_quantity >= 0)
);

CREATE INDEX IF NOT EXISTS idx_inventory_lines_session_id
  ON inventory_lines(session_id, id);

CREATE TABLE IF NOT EXISTS inventory_responsibles (
  session_id BIGINT NOT NULL REFERENCES inventory_sessions(id) ON DELETE CASCADE,
  responsible_id TEXT NOT NULL,
  PRIMARY KEY(session_id, responsible_id)
);

CREATE TABLE IF NOT EXISTS inventory_session_categories (
  session_id BIGINT NOT NULL REFERENCES inventory_sessions(id) ON DELETE CASCADE,
  category_id BIGINT NOT NULL REFERENCES categories(id),
  PRIMARY KEY(session_id, category_id)
);

CREATE TABLE IF NOT EXISTS supplier_price_history (
  id BIGSERIAL PRIMARY KEY,
  supplier_id BIGINT NOT NULL REFERENCES suppliers(id),
  product_id BIGINT NOT NULL REFERENCES products(id),
  batch_id BIGINT REFERENCES batches(id),
  lot TEXT,
  unit_price NUMERIC(18, 4) NOT NULL,
  source TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supplier_price_history_supplier_product_recorded
  ON supplier_price_history(supplier_id, product_id, recorded_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  warehouse_id BIGINT REFERENCES warehouses(id),
  payload JSONB NOT NULL,
  request_id TEXT,
  correlation_id TEXT,
  ip_address INET,
  user_agent TEXT,
  previous_hash TEXT,
  record_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_entity_created
  ON audit_log(entity_type, entity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_created
  ON audit_log(created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_warehouse_created
  ON audit_log(warehouse_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS notifications (
  id BIGSERIAL PRIMARY KEY,
  notification_type TEXT NOT NULL,
  product_id BIGINT REFERENCES products(id),
  batch_id BIGINT REFERENCES batches(id),
  device_id BIGINT REFERENCES sensor_devices(id),
  sensor_reading_id BIGINT REFERENCES sensor_readings(id),
  warehouse_id BIGINT REFERENCES warehouses(id),
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL,
  read_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_notifications_warehouse_read
  ON notifications(warehouse_id, is_read, created_at DESC, id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_unread_low_stock_warehouse_product
  ON notifications(warehouse_id, product_id)
  WHERE notification_type = 'low_stock' AND is_read = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_unread_expiry_warehouse_batch
  ON notifications(warehouse_id, batch_id)
  WHERE notification_type = 'expiry' AND is_read = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_unread_sensor_warning_device
  ON notifications(device_id)
  WHERE notification_type = 'sensor_warning' AND is_read = FALSE;

CREATE TABLE IF NOT EXISTS purchase_requests (
  id BIGSERIAL PRIMARY KEY,
  warehouse_id BIGINT NOT NULL REFERENCES warehouses(id),
  product_id BIGINT NOT NULL REFERENCES products(id),
  status TEXT NOT NULL,
  current_free_quantity NUMERIC(18, 3) NOT NULL,
  reorder_point NUMERIC(18, 3) NOT NULL,
  safety_stock NUMERIC(18, 3) NOT NULL DEFAULT 0,
  recommended_quantity NUMERIC(18, 3) NOT NULL,
  reason TEXT,
  source TEXT NOT NULL DEFAULT 'auto',
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT purchase_requests_status_check CHECK (status IN ('draft', 'ordered', 'cancelled')),
  CONSTRAINT purchase_requests_current_free_quantity_non_negative CHECK (current_free_quantity >= 0),
  CONSTRAINT purchase_requests_reorder_point_non_negative CHECK (reorder_point >= 0),
  CONSTRAINT purchase_requests_safety_stock_non_negative CHECK (safety_stock >= 0),
  CONSTRAINT purchase_requests_recommended_quantity_positive CHECK (recommended_quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_purchase_requests_warehouse_status_created
  ON purchase_requests(warehouse_id, status, created_at DESC, id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_requests_open_draft_product_warehouse
  ON purchase_requests(warehouse_id, product_id)
  WHERE status = 'draft';

CREATE TABLE IF NOT EXISTS abc_xyz_runs (
  id BIGSERIAL PRIMARY KEY,
  warehouse_id BIGINT REFERENCES warehouses(id),
  analysis_days INTEGER NOT NULL,
  period_start TIMESTAMPTZ NOT NULL,
  period_end TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  items_count INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  generated_by TEXT NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT abc_xyz_runs_analysis_days_positive CHECK (analysis_days > 0),
  CONSTRAINT abc_xyz_runs_items_count_non_negative CHECK (items_count >= 0),
  CONSTRAINT abc_xyz_runs_source_check CHECK (source IN ('manual', 'background')),
  CONSTRAINT abc_xyz_runs_status_check CHECK (status IN ('succeeded', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_abc_xyz_runs_warehouse_generated
  ON abc_xyz_runs(warehouse_id, generated_at DESC, id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_abc_xyz_runs_period
  ON abc_xyz_runs(COALESCE(warehouse_id, 0), analysis_days, period_start, period_end, source)
  WHERE status = 'succeeded';

CREATE TABLE IF NOT EXISTS abc_xyz_run_items (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES abc_xyz_runs(id) ON DELETE CASCADE,
  product_id BIGINT NOT NULL REFERENCES products(id),
  product_name TEXT NOT NULL,
  sku TEXT NOT NULL,
  abc_class TEXT NOT NULL,
  xyz_class TEXT NOT NULL,
  consumption_quantity NUMERIC(18, 3) NOT NULL,
  consumption_value NUMERIC(18, 3) NOT NULL,
  current_free_quantity NUMERIC(18, 3) NOT NULL,
  reorder_point NUMERIC(18, 3) NOT NULL,
  safety_stock NUMERIC(18, 3) NOT NULL,
  recommended_order_quantity NUMERIC(18, 3) NOT NULL,
  recommendation TEXT NOT NULL,
  movement_count INTEGER NOT NULL,
  CONSTRAINT abc_xyz_run_items_abc_check CHECK (abc_class IN ('A', 'B', 'C')),
  CONSTRAINT abc_xyz_run_items_xyz_check CHECK (xyz_class IN ('X', 'Y', 'Z')),
  CONSTRAINT abc_xyz_run_items_movement_count_non_negative CHECK (movement_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_abc_xyz_run_items_run
  ON abc_xyz_run_items(run_id, product_id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  id BIGSERIAL PRIMARY KEY,
  key TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  response_status INTEGER,
  response_body JSONB,
  resource_type TEXT,
  resource_id TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  locked_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  CONSTRAINT idempotency_keys_status_check CHECK (status IN ('processing', 'succeeded', 'failed')),
  UNIQUE(actor_id, key)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires
  ON idempotency_keys(expires_at);

CREATE TABLE IF NOT EXISTS outbox_events (
  id UUID PRIMARY KEY,
  event_type TEXT NOT NULL,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  warehouse_id BIGINT,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL,
  published_at TIMESTAMPTZ,
  CONSTRAINT outbox_events_status_check CHECK (status IN ('pending', 'published', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_status_created
  ON outbox_events(status, created_at);
