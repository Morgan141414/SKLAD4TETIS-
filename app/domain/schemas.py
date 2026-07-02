from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

try:
    from pydantic import BaseModel, ConfigDict, Field
except ModuleNotFoundError:
    _MISSING = object()

    class _FieldInfo:
        def __init__(self, default: Any = _MISSING, **_: Any) -> None:
            self.default = default

    def Field(default: Any = _MISSING, **kwargs: Any) -> Any:
        return _FieldInfo(default, **kwargs)

    def ConfigDict(**kwargs: Any) -> dict[str, Any]:
        return kwargs

    class BaseModel:
        def __init__(self, **kwargs: Any) -> None:
            for name in self._model_fields():
                if name in kwargs:
                    value = kwargs[name]
                else:
                    default = getattr(self.__class__, name, _MISSING)
                    if isinstance(default, _FieldInfo):
                        value = default.default
                    else:
                        value = default
                    if value is _MISSING:
                        raise TypeError(f"Missing required field: {name}")
                setattr(self, name, value)

        def model_dump(self, mode: str = "python") -> dict[str, Any]:
            return {
                name: _json_value(getattr(self, name))
                for name in self._model_fields()
            }

        @classmethod
        def _model_fields(cls) -> dict[str, Any]:
            fields: dict[str, Any] = {}
            for model_cls in reversed(cls.__mro__):
                fields.update(getattr(model_cls, "__annotations__", {}))
            return fields

    def _json_value(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [_json_value(item) for item in value]
        if isinstance(value, dict):
            return {key: _json_value(item) for key, item in value.items()}
        return value

from app.domain.enums import (
    BatchStatus,
    InventoryStatus,
    QuarantineReviewStatus,
    ReservationStatus,
    StockDocumentStatus,
    StockDocumentType,
)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CategoryUpdate(CategoryCreate):
    pass


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    bin: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=500)
    rating: int | None = Field(default=None, ge=1, le=5)
    is_preferred: bool = False
    contact_person: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    contract_number: str | None = Field(default=None, max_length=100)
    contract_expires_on: date | None = None
    payment_terms: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class SupplierUpdate(SupplierCreate):
    pass


class SupplierApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    bin: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    contact_person: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class SupplierApplicationReview(BaseModel):
    status: str = Field(pattern="^(approved|rejected|needs_changes|suspended)$")
    reason: str | None = Field(default=None, max_length=1000)
    supplier_id: int | None = None


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    tetis_org_id: str | None = Field(default=None, max_length=128)
    external_tetis_id: str | None = Field(default=None, max_length=128)
    storage_zone: str | None = Field(default=None, max_length=200)
    capacity_limit: Decimal | None = Field(default=None, ge=0)
    storage_conditions: str | None = Field(default=None, max_length=500)
    responsible_person: str | None = Field(default=None, max_length=200)


class WarehouseUpdate(WarehouseCreate):
    pass


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    sku: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=32)
    category_id: int
    reorder_point: Decimal = Decimal("0")
    safety_stock: Decimal = Decimal("0")
    is_controlled: bool = False
    barcode: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    certificate_ref: str | None = Field(default=None, max_length=500)


class ProductUpdate(ProductCreate):
    pass


class ReceiptCreate(BaseModel):
    product_id: int
    supplier_id: int
    warehouse_id: int
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    lot: str = Field(min_length=1, max_length=120)
    serial_number: str | None = Field(default=None, max_length=200)
    expires_on: date | None = None
    quarantine: bool = True


class ReceiptDocumentLineCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    lot: str = Field(min_length=1, max_length=120)
    serial_number: str | None = Field(default=None, max_length=200)
    expires_on: date | None = None
    quarantine: bool = True


class ReceiptDocumentCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    lines: list[ReceiptDocumentLineCreate]


class WriteOffCreate(BaseModel):
    batch_id: int
    warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    patient_id: str | None = None
    doctor_id: str | None = None
    medical_record_no: str | None = None
    second_approver_id: str | None = None
    second_approval_note: str | None = Field(default=None, max_length=500)


class WriteOffFefoCreate(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    patient_id: str | None = None
    doctor_id: str | None = None
    medical_record_no: str | None = None
    second_approver_id: str | None = None
    second_approval_note: str | None = Field(default=None, max_length=500)


class TransferCreate(BaseModel):
    batch_id: int
    source_warehouse_id: int
    target_warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(default="Внутреннее перемещение", min_length=1, max_length=500)


class TransferDocumentLineCreate(BaseModel):
    batch_id: int
    target_warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(default="Внутреннее перемещение", min_length=1, max_length=500)


class TransferDocumentCreate(BaseModel):
    source_warehouse_id: int
    lines: list[TransferDocumentLineCreate]


class DepartmentReturnDocumentLineCreate(BaseModel):
    batch_id: int
    target_warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class DepartmentReturnDocumentCreate(BaseModel):
    source_warehouse_id: int
    lines: list[DepartmentReturnDocumentLineCreate]


class SupplierReturnDocumentLineCreate(BaseModel):
    batch_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class SupplierReturnDocumentCreate(BaseModel):
    warehouse_id: int
    supplier_id: int
    lines: list[SupplierReturnDocumentLineCreate]


class RepackDocumentLineCreate(BaseModel):
    batch_id: int
    target_product_id: int
    quantity: Decimal = Field(gt=0)
    target_quantity: Decimal = Field(gt=0)
    conversion_factor: Decimal = Field(gt=0)
    loss_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    target_lot: str = Field(min_length=1, max_length=120)
    target_expires_on: date | None = None
    target_unit_price: Decimal | None = Field(default=None, ge=0)
    quarantine: bool = False
    reason: str = Field(default="Фасовка / переупаковка", min_length=1, max_length=500)


class RepackDocumentCreate(BaseModel):
    warehouse_id: int
    lines: list[RepackDocumentLineCreate]


class DepartmentReturnCreate(BaseModel):
    batch_id: int
    source_warehouse_id: int
    target_warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class SupplierReturnCreate(BaseModel):
    batch_id: int
    warehouse_id: int
    supplier_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class WriteOffDocumentLineCreate(BaseModel):
    batch_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    patient_id: str | None = None
    doctor_id: str | None = None
    medical_record_no: str | None = None
    second_approver_id: str | None = None
    second_approval_note: str | None = Field(default=None, max_length=500)


class WriteOffDocumentCreate(BaseModel):
    warehouse_id: int
    lines: list[WriteOffDocumentLineCreate]


class ReservationCreate(BaseModel):
    batch_id: int
    warehouse_id: int
    quantity: Decimal = Field(gt=0)
    reserved_for: str = Field(min_length=1, max_length=240)
    expires_at: datetime | None = None


class ReservationUseCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    patient_id: str | None = None
    doctor_id: str | None = None
    medical_record_no: str | None = None
    second_approver_id: str | None = None
    second_approval_note: str | None = Field(default=None, max_length=500)


class BatchStatusUpdate(BaseModel):
    status: BatchStatus
    reason: str | None = Field(default=None, max_length=500)


class BatchRecallCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    source: str = Field(default="manual", min_length=1, max_length=120)
    reference: str | None = Field(default=None, max_length=240)


class QuarantineReviewUpdate(BaseModel):
    status: QuarantineReviewStatus
    responsible_id: str | None = Field(default=None, max_length=120)
    due_at: datetime | None = None
    decision_reason: str | None = Field(default=None, max_length=1000)


class WarehouseLockUpdate(BaseModel):
    inventory_lock: bool


class NotificationReadUpdate(BaseModel):
    is_read: bool = True


class InventoryCreate(BaseModel):
    warehouse_id: int
    responsible_ids: list[str] = Field(default_factory=list, max_length=20)
    category_ids: list[int] = Field(default_factory=list, max_length=100)


class InventoryLineCountUpdate(BaseModel):
    actual_quantity: Decimal = Field(ge=0)


class Row(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class Category(Row):
    id: int
    name: str
    is_active: bool = True


class Supplier(Row):
    id: int
    name: str
    bin: str | None
    phone: str | None
    address: str | None = None
    rating: int | None = None
    is_preferred: bool = False
    contact_person: str | None = None
    email: str | None = None
    contract_number: str | None = None
    contract_expires_on: date | None = None
    payment_terms: str | None = None
    notes: str | None = None


class SupplierApplication(Row):
    id: int
    actor_id: str
    supplier_id: int | None = None
    status: str
    name: str
    bin: str | None = None
    phone: str | None = None
    email: str | None = None
    contact_person: str | None = None
    address: str | None = None
    notes: str | None = None
    review_reason: str | None = None
    submitted_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    supplier_name: str | None = None


class SupplierApplicationPage(BaseModel):
    items: list[SupplierApplication]
    total: int
    limit: int
    offset: int


class Warehouse(Row):
    id: int
    name: str
    department: str | None
    inventory_lock: bool
    tetis_org_id: str | None = None
    external_tetis_id: str | None = None
    storage_zone: str | None = None
    capacity_limit: Decimal | None = None
    storage_conditions: str | None = None
    responsible_person: str | None = None


class TetisWarehouseMapping(Row):
    tetis_org_id: str
    warehouse_ids: list[int]


class SensorDeviceCreate(BaseModel):
    warehouse_id: int
    name: str = Field(min_length=1, max_length=200)
    serial_number: str | None = Field(default=None, max_length=200)
    sensor_type: str = Field(default="temperature_humidity", min_length=1, max_length=80)
    min_temperature_c: Decimal | None = None
    max_temperature_c: Decimal | None = None
    min_humidity_percent: Decimal | None = None
    max_humidity_percent: Decimal | None = None


class SensorDeviceUpdate(SensorDeviceCreate):
    pass


class SensorDevice(Row):
    id: int
    warehouse_id: int
    name: str
    serial_number: str | None
    sensor_type: str
    min_temperature_c: Decimal | None
    max_temperature_c: Decimal | None
    min_humidity_percent: Decimal | None
    max_humidity_percent: Decimal | None
    created_at: datetime
    updated_at: datetime


class SensorReadingCreate(BaseModel):
    device_id: int
    temperature_c: Decimal | None = None
    humidity_percent: Decimal | None = None
    recorded_at: datetime | None = None
    raw_payload: str | None = Field(default=None, max_length=2000)


class SensorReading(Row):
    id: int
    device_id: int
    warehouse_id: int
    temperature_c: Decimal | None
    humidity_percent: Decimal | None
    recorded_at: datetime
    received_at: datetime
    status: str
    raw_payload: str | None
    device_name: str | None = None
    warehouse_name: str | None = None


class SensorReadingPage(BaseModel):
    items: list[SensorReading]
    total: int
    limit: int
    offset: int


class Product(Row):
    id: int
    name: str
    sku: str
    unit: str
    category_id: int
    reorder_point: Decimal
    safety_stock: Decimal
    is_controlled: bool
    barcode: str | None = None
    description: str | None = None
    certificate_ref: str | None = None
    is_active: bool = True


class ProductBarcodeLabel(BaseModel):
    product_id: int
    name: str
    sku: str
    barcode: str
    symbology: str
    label_text: str
    zpl: str
    epl: str


class ProductBarcodeLabelBatchRequest(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=200)


class ProductBarcodeLabelBatch(BaseModel):
    labels: list[ProductBarcodeLabel]
    zpl: str
    epl: str


class Batch(Row):
    id: int
    product_id: int
    supplier_id: int
    received_at: datetime
    lot: str
    serial_number: str | None = None
    expires_on: date | None
    unit_price: Decimal
    status: BatchStatus


class BatchPriceLabel(BaseModel):
    batch_id: int
    product_id: int
    name: str
    sku: str
    lot: str
    serial_number: str | None = None
    expires_on: date | None
    unit_price: Decimal
    barcode: str
    symbology: str
    label_text: str
    zpl: str
    epl: str


class BatchPriceLabelBatchRequest(BaseModel):
    batch_ids: list[int] = Field(min_length=1, max_length=200)


class BatchPriceLabelBatch(BaseModel):
    labels: list[BatchPriceLabel]
    zpl: str
    epl: str


class SupplierPriceHistoryEntry(Row):
    id: int
    supplier_id: int
    supplier_name: str
    product_id: int
    product_name: str
    sku: str
    batch_id: int | None
    lot: str | None
    unit_price: Decimal
    source: str
    recorded_at: datetime


class SupplierPriceHistoryPage(BaseModel):
    items: list[SupplierPriceHistoryEntry]
    total: int
    limit: int
    offset: int


class Balance(Row):
    product_id: int
    batch_id: int
    warehouse_id: int
    total_quantity: Decimal
    reserved_quantity: Decimal
    free_quantity: Decimal
    batch_status: BatchStatus
    expires_on: date | None


class BalancePage(BaseModel):
    items: list[Balance]
    total: int
    limit: int
    offset: int


class BatchDetail(BaseModel):
    batch: Batch
    balances: list[Balance]
    movements: list["SafeStockMovement"]


class BatchTraceability(BatchDetail):
    documents: list["SafeStockDocumentDetail"]
    transformations: list["BatchTransformation"] = []
    recalls: list["BatchRecall"] = []


class QuarantineReview(Row):
    id: int
    batch_id: int
    product_id: int
    product_name: str
    lot: str
    warehouse_id: int
    status: QuarantineReviewStatus
    responsible_id: str | None
    due_at: datetime | None
    decision_reason: str | None
    created_by: str
    decided_by: str | None
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None


class QuarantineReviewPage(BaseModel):
    items: list[QuarantineReview]
    total: int
    limit: int
    offset: int


class QuarantineReviewProtocol(BaseModel):
    review_id: int
    batch_id: int
    product_name: str
    lot: str
    warehouse_id: int
    warehouse_name: str
    status: QuarantineReviewStatus
    responsible_id: str | None
    due_at: datetime | None
    decision_reason: str | None
    created_by: str
    decided_by: str | None
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    csv: str


class Reservation(Row):
    id: int
    batch_id: int
    warehouse_id: int
    quantity: Decimal
    reserved_for: str
    status: ReservationStatus
    expires_at: datetime | None
    created_at: datetime


class StockMovement(Row):
    id: int
    movement_type: str
    batch_id: int
    warehouse_id: int
    quantity: Decimal
    reason: str | None
    patient_id: str | None
    doctor_id: str | None
    medical_record_no: str | None
    second_approver_id: str | None = None
    second_approval_note: str | None = None
    created_at: datetime


class SafeStockMovement(Row):
    id: int
    movement_type: str
    batch_id: int
    warehouse_id: int
    quantity: Decimal
    reason: str | None
    created_at: datetime


class StockMovementPage(BaseModel):
    items: list[SafeStockMovement]
    total: int
    limit: int
    offset: int


class ControlledSubstanceLedgerEntry(Row):
    movement_id: int
    movement_type: str
    product_id: int
    product_name: str
    sku: str
    batch_id: int
    lot: str
    warehouse_id: int
    quantity: Decimal
    reason: str | None
    patient_id: str | None
    doctor_id: str | None
    medical_record_no: str | None
    second_approver_id: str | None = None
    second_approval_note: str | None = None
    created_at: datetime


class ControlledSubstanceLedgerPage(BaseModel):
    items: list[ControlledSubstanceLedgerEntry]
    total: int
    limit: int
    offset: int


class ControlledSubstanceLedgerExport(BaseModel):
    filename: str
    csv: str


class TransferResult(BaseModel):
    batch_id: int
    source_warehouse_id: int
    target_warehouse_id: int
    quantity: Decimal
    out_movement_id: int
    in_movement_id: int


class FefoWriteOffResult(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: Decimal
    movement_ids: list[int]


class SupplierReturnResult(BaseModel):
    batch_id: int
    warehouse_id: int
    supplier_id: int
    quantity: Decimal
    movement_id: int


class StockDocument(Row):
    id: int
    document_type: StockDocumentType
    status: StockDocumentStatus
    warehouse_id: int
    supplier_id: int | None
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    posted_at: datetime | None


class StockDocumentLine(Row):
    id: int
    document_id: int
    product_id: int | None
    batch_id: int | None
    target_warehouse_id: int | None
    target_product_id: int | None = None
    quantity: Decimal
    target_quantity: Decimal | None = None
    conversion_factor: Decimal | None = None
    loss_quantity: Decimal | None = None
    unit_price: Decimal | None
    target_unit_price: Decimal | None = None
    lot: str | None
    serial_number: str | None = None
    target_lot: str | None = None
    expires_on: date | None
    target_expires_on: date | None = None
    quarantine: bool
    reason: str | None
    patient_id: str | None
    doctor_id: str | None
    medical_record_no: str | None
    second_approver_id: str | None = None
    second_approval_note: str | None = None


class StockDocumentDetail(StockDocument):
    lines: list[StockDocumentLine]


class SafeStockDocument(StockDocument):
    pass


class SafeStockDocumentLine(Row):
    id: int
    document_id: int
    product_id: int | None
    batch_id: int | None
    target_warehouse_id: int | None
    target_product_id: int | None = None
    quantity: Decimal
    target_quantity: Decimal | None = None
    conversion_factor: Decimal | None = None
    loss_quantity: Decimal | None = None
    unit_price: Decimal | None
    target_unit_price: Decimal | None = None
    lot: str | None
    serial_number: str | None = None
    target_lot: str | None = None
    expires_on: date | None
    target_expires_on: date | None = None
    quarantine: bool
    reason: str | None


class SafeStockDocumentDetail(SafeStockDocument):
    lines: list[SafeStockDocumentLine]


class RepackPrintLine(BaseModel):
    line_no: int
    source_batch_id: int
    source_product_name: str
    source_lot: str
    target_batch_id: int | None
    target_product_name: str
    target_lot: str
    source_quantity: Decimal
    target_quantity: Decimal
    conversion_factor: Decimal
    loss_quantity: Decimal
    target_unit_price: Decimal | None = None
    reason: str | None = None


class RepackPrintForm(BaseModel):
    document_id: int
    status: StockDocumentStatus
    warehouse_id: int
    warehouse_name: str
    created_by: str
    created_at: datetime
    posted_at: datetime | None
    csv: str
    lines: list[RepackPrintLine]


class TransferPrintLine(BaseModel):
    line_no: int
    batch_id: int
    product_name: str
    lot: str
    source_warehouse_id: int
    source_warehouse_name: str
    target_warehouse_id: int
    target_warehouse_name: str
    quantity: Decimal
    reason: str | None = None


class TransferPrintForm(BaseModel):
    document_id: int
    status: StockDocumentStatus
    source_warehouse_id: int
    source_warehouse_name: str
    created_by: str
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    posted_at: datetime | None
    csv: str
    lines: list[TransferPrintLine]


class StockDocumentPage(BaseModel):
    items: list[SafeStockDocumentDetail]
    total: int
    limit: int
    offset: int


class BatchTransformation(Row):
    id: int
    document_id: int | None
    source_batch_id: int
    target_batch_id: int
    warehouse_id: int
    source_product_id: int
    target_product_id: int
    source_product_name: str | None = None
    target_product_name: str | None = None
    source_lot: str | None = None
    target_lot: str | None = None
    source_quantity: Decimal
    target_quantity: Decimal
    conversion_factor: Decimal
    loss_quantity: Decimal
    reason: str | None
    created_by: str
    created_at: datetime


class BatchTransformationPage(BaseModel):
    items: list[BatchTransformation]
    total: int
    limit: int
    offset: int


class BatchRecall(Row):
    id: int
    batch_id: int
    product_id: int
    product_name: str | None = None
    lot: str | None = None
    reason: str
    source: str
    reference: str | None
    created_by: str
    created_at: datetime


class BatchRecallPage(BaseModel):
    items: list[BatchRecall]
    total: int
    limit: int
    offset: int


class BatchRecallResult(BaseModel):
    recall: BatchRecall
    batch: Batch
    affected_warehouses: list[Balance]
    notifications: list["Notification"]


class Notification(Row):
    id: int
    notification_type: str
    product_id: int | None
    batch_id: int | None
    device_id: int | None = None
    sensor_reading_id: int | None = None
    warehouse_id: int | None
    title: str
    message: str
    is_read: bool
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[Notification]
    total: int
    limit: int
    offset: int


class PurchaseRequest(Row):
    id: int
    warehouse_id: int
    product_id: int
    product_name: str
    sku: str
    status: str
    current_free_quantity: Decimal
    reorder_point: Decimal
    safety_stock: Decimal
    recommended_quantity: Decimal
    reason: str | None = None
    source: str
    created_by: str
    created_at: datetime
    offer_id: int | None = None
    offer_status: str | None = None
    offer_unit_price: Decimal | None = None
    offer_quantity: Decimal | None = None
    offer_delivery_date: date | None = None
    offer_expires_at: date | None = None
    offer_comment: str | None = None


class PurchaseRequestCreate(BaseModel):
    warehouse_id: int
    product_id: int
    quantity: Decimal = Field(gt=0)
    reason: str = Field(default="Пополнение склада", min_length=1, max_length=500)
    source: str = Field(default="manual", min_length=1, max_length=80)


class PurchaseRequestStatusUpdate(BaseModel):
    status: str = Field(pattern="^(ordered|cancelled)$")


class SupplierOfferCreate(BaseModel):
    purchase_request_id: int
    unit_price: Decimal = Field(ge=0)
    quantity: Decimal = Field(gt=0)
    delivery_date: date | None = None
    expires_at: date | None = None
    comment: str | None = Field(default=None, max_length=1000)


class SupplierOfferReview(BaseModel):
    status: str = Field(pattern="^(accepted|rejected)$")
    reason: str | None = Field(default=None, max_length=1000)


class SupplierOffer(Row):
    id: int
    purchase_request_id: int
    supplier_id: int
    actor_id: str
    status: str
    unit_price: Decimal
    quantity: Decimal
    delivery_date: date | None = None
    expires_at: date | None = None
    comment: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    supplier_name: str | None = None
    product_name: str | None = None
    sku: str | None = None
    warehouse_id: int | None = None
    request_status: str | None = None


class SupplierCatalogCreate(BaseModel):
    type: str = Field(default="product", pattern="^(product|service)$")
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    price: Decimal | None = Field(default=None, ge=0)
    price_type: str = Field(default="fixed", pattern="^(fixed|hourly|negotiable)$")
    unit: str | None = Field(default=None, max_length=64)
    service_category: str | None = Field(default=None, pattern="^(repair|cleaning|logistics|consulting|)$")


class SupplierCatalogUpdate(SupplierCatalogCreate):
    pass


class SupplierCatalog(Row):
    id: int
    supplier_id: int
    actor_id: str
    type: str
    title: str
    description: str | None = None
    price: Decimal | None = None
    price_type: str
    unit: str | None = None
    service_category: str | None = None
    image_file_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    supplier_name: str | None = None


class SupplierCatalogPage(BaseModel):
    items: list[SupplierCatalog]
    total: int
    limit: int
    offset: int


class AuditLogEntry(Row):
    id: int
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    warehouse_id: int | None
    payload: dict[str, Any]
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogEntry]
    total: int
    limit: int
    offset: int


class AbcXyzAnalysisItem(BaseModel):
    product_id: int
    product_name: str
    sku: str
    abc_class: str
    xyz_class: str
    consumption_quantity: Decimal
    consumption_value: Decimal
    current_free_quantity: Decimal
    reorder_point: Decimal
    safety_stock: Decimal
    recommended_order_quantity: Decimal
    recommendation: str
    movement_count: int


class AbcXyzAnalysis(BaseModel):
    items: list[AbcXyzAnalysisItem]
    analysis_days: int
    warehouse_id: int | None
    generated_at: datetime


class AbcXyzRun(Row):
    id: int
    warehouse_id: int | None
    analysis_days: int
    period_start: datetime
    period_end: datetime
    source: str
    status: str
    items_count: int
    error: str | None = None
    generated_by: str
    generated_at: datetime


class AbcXyzRunDetail(AbcXyzRun):
    items: list[AbcXyzAnalysisItem]


class AbcXyzRunPage(BaseModel):
    items: list[AbcXyzRun]
    total: int
    limit: int
    offset: int


class InventorySession(Row):
    id: int
    warehouse_id: int
    status: InventoryStatus
    started_by: str
    posted_by: str | None
    started_at: datetime
    posted_at: datetime | None
    cancelled_at: datetime | None
    responsible_ids: list[str] = Field(default_factory=list)
    category_ids: list[int] = Field(default_factory=list)


class InventoryLine(Row):
    id: int
    session_id: int
    product_id: int
    batch_id: int
    expected_quantity: Decimal
    actual_quantity: Decimal | None
    difference_quantity: Decimal | None


class InventorySummary(BaseModel):
    total_lines: int
    filled_lines: int
    missing_lines: int
    surplus_lines: int
    shortage_lines: int
    matched_lines: int
    total_expected_quantity: Decimal
    total_actual_quantity: Decimal
    total_surplus_quantity: Decimal
    total_shortage_quantity: Decimal


class InventorySessionDetail(InventorySession):
    lines: list[InventoryLine]
    summary: InventorySummary


class InventoryPrintLine(BaseModel):
    line_no: int
    product_id: int
    product_name: str
    sku: str
    unit: str
    batch_id: int
    lot: str
    expires_on: date | None
    expected_quantity: Decimal
    actual_quantity: Decimal | None
    difference_quantity: Decimal | None


class InventoryPrintForm(BaseModel):
    session_id: int
    warehouse_id: int
    warehouse_name: str
    status: InventoryStatus
    started_by: str
    posted_by: str | None
    started_at: datetime
    posted_at: datetime | None
    summary: InventorySummary
    count_sheet_csv: str
    reconciliation_csv: str
    lines: list[InventoryPrintLine]
