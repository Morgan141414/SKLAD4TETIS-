import logging
import urllib.request
from datetime import date

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.domain.errors import (
    AuthenticationError,
    BatchUnavailableError,
    ConflictError,
    InsufficientStockError,
    InventoryLockedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.schemas import (
    AbcXyzAnalysis,
    AbcXyzRunDetail,
    AbcXyzRunPage,
    AuditLogEntry,
    AuditLogPage,
    Balance,
    BalancePage,
    BatchDetail,
    BatchPriceLabel,
    BatchPriceLabelBatch,
    BatchPriceLabelBatchRequest,
    BatchStatusUpdate,
    Batch,
    BatchRecallCreate,
    BatchRecallPage,
    BatchRecallResult,
    BatchTransformationPage,
    BatchTraceability,
    Category,
    CategoryCreate,
    CategoryUpdate,
    ControlledSubstanceLedgerPage,
    ControlledSubstanceLedgerExport,
    DepartmentReturnDocumentCreate,
    DepartmentReturnCreate,
    FefoWriteOffResult,
    InventoryCreate,
    InventoryPrintForm,
    InventoryLine,
    InventoryLineCountUpdate,
    InventorySessionDetail,
    Notification,
    NotificationPage,
    ProductCreate,
    NotificationReadUpdate,
    Product,
    ProductBarcodeLabel,
    ProductBarcodeLabelBatch,
    ProductBarcodeLabelBatchRequest,
    PurchaseRequest,
    PurchaseRequestCreate,
    PurchaseRequestStatusUpdate,
    ProductUpdate,
    QuarantineReview,
    QuarantineReviewPage,
    QuarantineReviewProtocol,
    QuarantineReviewUpdate,
    ReceiptCreate,
    ReceiptDocumentCreate,
    RepackDocumentCreate,
    RepackPrintForm,
    Reservation,
    ReservationCreate,
    ReservationUseCreate,
    SafeStockDocumentDetail,
    SafeStockMovement,
    SensorDevice,
    SensorDeviceCreate,
    SensorDeviceUpdate,
    SensorReading,
    SensorReadingCreate,
    SensorReadingPage,
    StockDocumentDetail,
    StockDocumentPage,
    StockMovement,
    StockMovementPage,
    Supplier,
    SupplierApplication,
    SupplierApplicationCreate,
    SupplierApplicationPage,
    SupplierApplicationReview,
    SupplierCatalog,
    SupplierCatalogCreate,
    SupplierCatalogPage,
    SupplierCatalogUpdate,
    SupplierCreate,
    SupplierOffer,
    SupplierOfferCreate,
    SupplierOfferReview,
    SupplierPriceHistoryPage,
    SupplierUpdate,
    SupplierReturnDocumentCreate,
    SupplierReturnResult,
    SupplierReturnCreate,
    TetisWarehouseMapping,
    TransferCreate,
    TransferDocumentCreate,
    TransferPrintForm,
    TransferResult,
    Warehouse,
    WarehouseCreate,
    WarehouseLockUpdate,
    WarehouseUpdate,
    WriteOffCreate,
    WriteOffFefoCreate,
    WriteOffDocumentCreate,
)
from app.services.idempotency import IdempotencyStore, run_idempotent
from app.services.warehouse import WarehouseService
from app.realtime.manager import manager
from app.security.rbac import (
    ActorContext,
    Permission,
    Role,
    actor_from_headers,
    require_permission,
    require_stock_access,
    require_warehouse_filter,
)
from app.security.tokens import actor_from_bearer_token

from .dependencies import (
    get_actor_context,
    get_database_readiness,
    get_idempotency_store,
    get_warehouse_service,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness():
    readiness_status = get_database_readiness()
    if readiness_status["status"] != "ok":
        details = {
            key: value
            for key, value in readiness_status.items()
            if key not in {"status", "detail"}
        }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": readiness_status["detail"],
                "details": details,
            },
        )
    return readiness_status


@router.get("/me")
def current_actor(actor_ctx: ActorContext = Depends(get_actor_context)):
    return {
        "actor_id": actor_ctx.actor_id,
        "roles": sorted(role.value for role in actor_ctx.roles),
        "warehouse_ids": sorted(actor_ctx.warehouse_ids),
        "department": actor_ctx.department,
        "permissions": sorted(permission.value for permission in actor_ctx.permissions),
    }


def actor(actor_ctx: ActorContext = Depends(get_actor_context)) -> str:
    return actor_ctx.actor_id


def map_error(error: Exception) -> HTTPException:
    if isinstance(error, NotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": str(error), "details": {}},
        )
    if isinstance(error, (ConflictError, InsufficientStockError, InventoryLockedError, BatchUnavailableError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "message": str(error), "details": {}},
        )
    if isinstance(error, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": str(error), "details": {}},
        )
    if isinstance(error, ValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": str(error), "details": {}},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "internal_error", "message": "Internal error", "details": {}},
    )


async def publish_event(event: str, payload: dict) -> None:
    try:
        await manager.broadcast(event, payload)
    except Exception:
        logger.exception("Failed to publish realtime event %s", event)


def require_batch_read_scope(
    service: WarehouseService, actor_ctx: ActorContext, batch_id: int
) -> None:
    warehouse_ids = service.get_batch_warehouse_ids(batch_id)
    if not warehouse_ids:
        require_permission(actor_ctx, Permission.STOCK_READ)
        return
    for warehouse_id in warehouse_ids:
        require_stock_access(actor_ctx, Permission.STOCK_READ, warehouse_id)


@router.post("/categories", status_code=status.HTTP_201_CREATED, response_model=Category)
def create_category(
    data: CategoryCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.create_category(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/categories", response_model=list[Category])
def list_categories(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_categories(safe_limit, safe_offset, q=q)
    except Exception as error:
        raise map_error(error) from error


@router.patch("/categories/{category_id}", response_model=Category)
def update_category(
    category_id: int,
    data: CategoryUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.update_category(category_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.delete("/categories/{category_id}", response_model=Category)
def delete_category(
    category_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.delete_category(category_id, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/suppliers", status_code=status.HTTP_201_CREATED, response_model=Supplier)
def create_supplier(
    data: SupplierCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.create_supplier(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/suppliers", response_model=list[Supplier])
def list_suppliers(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_suppliers(safe_limit, safe_offset, q=q)
    except Exception as error:
        raise map_error(error) from error


@router.get("/suppliers/{supplier_id}/price-history", response_model=SupplierPriceHistoryPage)
def list_supplier_price_history(
    supplier_id: int,
    product_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_supplier_price_history(supplier_id, product_id, safe_limit, safe_offset),
            "total": service.count_supplier_price_history(supplier_id, product_id),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.patch("/suppliers/{supplier_id}", response_model=Supplier)
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.update_supplier(supplier_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/supplier-application/me", response_model=SupplierApplication | None)
def get_my_supplier_application(
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.get_supplier_application_for_actor(actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/supplier-application",
    status_code=status.HTTP_201_CREATED,
    response_model=SupplierApplication,
)
def submit_supplier_application(
    data: SupplierApplicationCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.submit_supplier_application(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/supplier-applications", response_model=SupplierApplicationPage)
def list_supplier_applications(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.ADMIN_USERS)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_supplier_applications(status, safe_limit, safe_offset),
            "total": service.count_supplier_applications(status),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.patch("/supplier-applications/{application_id}/review", response_model=SupplierApplication)
def review_supplier_application(
    application_id: int,
    data: SupplierApplicationReview,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.ADMIN_USERS)
        return service.review_supplier_application(application_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/warehouses", status_code=status.HTTP_201_CREATED, response_model=Warehouse)
def create_warehouse(
    data: WarehouseCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.create_warehouse(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/warehouses", response_model=list[Warehouse])
def list_warehouses(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_warehouses(safe_limit, safe_offset, q=q)
    except Exception as error:
        raise map_error(error) from error


@router.get("/tetis/orgs/{tetis_org_id}/warehouse-ids", response_model=TetisWarehouseMapping)
def resolve_tetis_warehouse_ids(
    tetis_org_id: str,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.ADMIN_USERS)
        return {
            "tetis_org_id": tetis_org_id.strip(),
            "warehouse_ids": service.list_warehouse_ids_for_tetis_org(tetis_org_id),
        }
    except Exception as error:
        raise map_error(error) from error


@router.patch("/warehouses/{warehouse_id}", response_model=Warehouse)
def update_warehouse(
    warehouse_id: int,
    data: WarehouseUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.update_warehouse(warehouse_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.patch("/warehouses/{warehouse_id}/inventory-lock", response_model=Warehouse)
def set_inventory_lock(
    warehouse_id: int,
    data: WarehouseLockUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_stock_access(actor_ctx, Permission.INVENTORY_MANAGE, warehouse_id)
        return service.set_inventory_lock(warehouse_id, data.inventory_lock, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/sensor-devices", status_code=status.HTTP_201_CREATED, response_model=SensorDevice)
def create_sensor_device(
    data: SensorDeviceCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_stock_access(actor_ctx, Permission.CATALOG_WRITE, data.warehouse_id)
        return service.create_sensor_device(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/sensor-devices", response_model=list[SensorDevice])
def list_sensor_devices(
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_sensor_devices(warehouse_id, safe_limit, safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.patch("/sensor-devices/{device_id}", response_model=SensorDevice)
def update_sensor_device(
    device_id: int,
    data: SensorDeviceUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        current = service.get_sensor_device(device_id)
        require_stock_access(actor_ctx, Permission.CATALOG_WRITE, current["warehouse_id"])
        require_stock_access(actor_ctx, Permission.CATALOG_WRITE, data.warehouse_id)
        return service.update_sensor_device(device_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/sensor-readings", status_code=status.HTTP_201_CREATED, response_model=SensorReading)
async def record_sensor_reading(
    data: SensorReadingCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        device = service.get_sensor_device(data.device_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, device["warehouse_id"])
        reading = service.record_sensor_reading(data, actor_id)
        await publish_event(
            "sensor.reading.created",
            {
                "device_id": reading["device_id"],
                "warehouse_id": reading["warehouse_id"],
                "temperature_c": reading["temperature_c"],
                "humidity_percent": reading["humidity_percent"],
                "status": reading["status"],
            },
        )
        if reading["status"] == "warning":
            await publish_event(
                "notifications.updated",
                {
                    "notification_type": "sensor_warning",
                    "warehouse_id": reading["warehouse_id"],
                    "device_id": reading["device_id"],
                },
            )
        return reading
    except Exception as error:
        raise map_error(error) from error


@router.get("/sensor-readings", response_model=SensorReadingPage)
def list_sensor_readings(
    warehouse_id: int | None = None,
    device_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        if device_id is not None:
            device = service.get_sensor_device(device_id)
            require_stock_access(actor_ctx, Permission.STOCK_READ, device["warehouse_id"])
        else:
            require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_sensor_readings(
                warehouse_id=warehouse_id,
                device_id=device_id,
                limit=safe_limit,
                offset=safe_offset,
            ),
            "total": service.count_sensor_readings(
                warehouse_id=warehouse_id,
                device_id=device_id,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/product-units", response_model=list[str])
def list_product_units(
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        return service.list_product_units()
    except Exception as error:
        raise map_error(error) from error


@router.get("/products", response_model=list[Product])
def list_products(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_products(safe_limit, safe_offset, q=q)
    except Exception as error:
        raise map_error(error) from error


@router.post("/products", status_code=status.HTTP_201_CREATED, response_model=Product)
def create_product(
    data: ProductCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.create_product(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.patch("/products/{product_id}", response_model=Product)
def update_product(
    product_id: int,
    data: ProductUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.update_product(product_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.delete("/products/{product_id}", response_model=Product)
def delete_product(
    product_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        require_permission(actor_ctx, Permission.CATALOG_WRITE)
        return service.delete_product(product_id, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/products/{product_id}/barcode-label", response_model=ProductBarcodeLabel)
def get_product_barcode_label(
    product_id: int,
    symbology: str = "code128",
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        return service.get_product_barcode_label(product_id, symbology=symbology)
    except Exception as error:
        raise map_error(error) from error


@router.post("/products/barcode-labels", response_model=ProductBarcodeLabelBatch)
def get_product_barcode_labels(
    data: ProductBarcodeLabelBatchRequest,
    symbology: str = "code128",
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        return service.get_product_barcode_labels(data.product_ids, symbology=symbology)
    except Exception as error:
        raise map_error(error) from error


@router.get("/batches", response_model=list[Batch])
def list_batches(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    supplier_id: int | None = None,
    status: str | None = None,
    expires_before: date | None = None,
    expires_after: date | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_batches(
            warehouse_id=warehouse_id,
            limit=safe_limit,
            offset=safe_offset,
            product_id=product_id,
            supplier_id=supplier_id,
            status=status,
            expires_before=expires_before,
            expires_after=expires_after,
        )
    except Exception as error:
        raise map_error(error) from error


@router.post("/batches/price-labels", response_model=BatchPriceLabelBatch)
def get_batch_price_labels(
    data: BatchPriceLabelBatchRequest,
    symbology: str = "code128",
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        return service.get_batch_price_labels(data.batch_ids, symbology=symbology)
    except Exception as error:
        raise map_error(error) from error


@router.get("/batches/{batch_id}", response_model=BatchDetail)
def get_batch(
    batch_id: int,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_batch_read_scope(service, actor_ctx, batch_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.get_batch_detail(batch_id, safe_limit, safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.get("/batches/{batch_id}/price-label", response_model=BatchPriceLabel)
def get_batch_price_label(
    batch_id: int,
    symbology: str = "code128",
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_batch_read_scope(service, actor_ctx, batch_id)
        return service.get_batch_price_label(batch_id, symbology=symbology)
    except Exception as error:
        raise map_error(error) from error


@router.get("/batches/{batch_id}/movements", response_model=list[SafeStockMovement])
def get_batch_movements(
    batch_id: int,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_batch_read_scope(service, actor_ctx, batch_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_stock_movements(batch_id=batch_id, limit=safe_limit, offset=safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.get("/batches/{batch_id}/traceability", response_model=BatchTraceability)
def get_batch_traceability(
    batch_id: int,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_batch_read_scope(service, actor_ctx, batch_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.get_batch_traceability(batch_id, safe_limit, safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.post("/batches/{batch_id}/recall", response_model=BatchRecallResult)
async def recall_batch(
    batch_id: int,
    data: BatchRecallCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        warehouse_ids = service.get_batch_warehouse_ids(batch_id)
        for warehouse_id in warehouse_ids:
            require_stock_access(actor_ctx, Permission.DOCUMENT_POST, warehouse_id)
        result, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/batches/{batch_id}/recall",
            payload=data,
            response_status=status.HTTP_200_OK,
            resource_type="batch_recall",
            operation=lambda: service.recall_batch(batch_id, data, actor_id),
        )
        if not replayed:
            await publish_event(
                "batch.recalled",
                {
                    "batch_id": batch_id,
                    "warehouse_ids": [row["warehouse_id"] for row in result["affected_warehouses"]],
                },
            )
            await publish_event(
                "batch.status.updated",
                {"batch_id": batch_id, "status": result["batch"]["status"]},
            )
        return result
    except Exception as error:
        raise map_error(error) from error


@router.get("/batch-recalls", response_model=BatchRecallPage)
def list_batch_recalls(
    batch_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        if batch_id is not None:
            require_batch_read_scope(service, actor_ctx, batch_id)
        elif actor_ctx.warehouse_ids:
            raise PermissionDeniedError("Batch filter is required for scoped actor")
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_batch_recalls(batch_id=batch_id, limit=safe_limit, offset=safe_offset),
            "total": service.count_batch_recalls(batch_id=batch_id),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.post("/receipts", status_code=status.HTTP_201_CREATED, response_model=Batch)
async def receive(
    data: ReceiptCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_RECEIVE, data.warehouse_id)
        batch, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/receipts",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="batch",
            operation=lambda: service.receive(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.balance.updated",
                {"product_id": data.product_id, "batch_id": batch["id"], "warehouse_id": data.warehouse_id},
            )
        return batch
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/stock-documents/receipts",
    status_code=status.HTTP_201_CREATED,
    response_model=StockDocumentDetail,
)
def create_receipt_document(
    data: ReceiptDocumentCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, data.warehouse_id)
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/stock-documents/receipts",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_document",
            operation=lambda: service.create_receipt_document(data, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/stock-documents/write-offs",
    status_code=status.HTTP_201_CREATED,
    response_model=StockDocumentDetail,
)
def create_writeoff_document(
    data: WriteOffDocumentCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, data.warehouse_id)
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/stock-documents/write-offs",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_document",
            operation=lambda: service.create_writeoff_document(data, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/stock-documents/transfers",
    status_code=status.HTTP_201_CREATED,
    response_model=StockDocumentDetail,
)
def create_transfer_document(
    data: TransferDocumentCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, data.source_warehouse_id)
        for line in data.lines:
            require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, line.target_warehouse_id)
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/stock-documents/transfers",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_document",
            operation=lambda: service.create_transfer_document(data, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/stock-documents/returns/from-department",
    status_code=status.HTTP_201_CREATED,
    response_model=StockDocumentDetail,
)
def create_department_return_document(
    data: DepartmentReturnDocumentCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, data.source_warehouse_id)
        for line in data.lines:
            require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, line.target_warehouse_id)
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/stock-documents/returns/from-department",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_document",
            operation=lambda: service.create_department_return_document(data, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/stock-documents/returns/to-supplier",
    status_code=status.HTTP_201_CREATED,
    response_model=StockDocumentDetail,
)
def create_supplier_return_document(
    data: SupplierReturnDocumentCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, data.warehouse_id)
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/stock-documents/returns/to-supplier",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_document",
            operation=lambda: service.create_supplier_return_document(data, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.get("/stock-documents/{document_id}", response_model=SafeStockDocumentDetail)
def get_stock_document(
    document_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        document = service.get_stock_document(document_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, document["warehouse_id"])
        return document
    except Exception as error:
        raise map_error(error) from error


@router.get("/stock-documents/{document_id}/repack-print-form", response_model=RepackPrintForm)
def get_repack_print_form(
    document_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        form = service.get_repack_print_form(document_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, form["warehouse_id"])
        return form
    except Exception as error:
        raise map_error(error) from error


@router.get("/stock-documents/{document_id}/transfer-print-form", response_model=TransferPrintForm)
def get_transfer_print_form(
    document_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        form = service.get_transfer_print_form(document_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, form["source_warehouse_id"])
        for line in form["lines"]:
            require_stock_access(actor_ctx, Permission.STOCK_READ, line["target_warehouse_id"])
        return form
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/stock-documents/repack",
    status_code=status.HTTP_201_CREATED,
    response_model=StockDocumentDetail,
)
def create_repack_document(
    data: RepackDocumentCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, data.warehouse_id)
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/stock-documents/repack",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_document",
            operation=lambda: service.create_repack_document(data, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.get("/stock-documents", response_model=StockDocumentPage)
def list_stock_documents(
    warehouse_id: int | None = None,
    document_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        items = [
            service.get_stock_document(document["id"])
            for document in service.list_stock_documents(
                warehouse_id=warehouse_id,
                limit=safe_limit,
                offset=safe_offset,
                document_type=document_type,
                status=status,
            )
        ]
        return {
            "items": items,
            "total": service.count_stock_documents(
                warehouse_id=warehouse_id,
                document_type=document_type,
                status=status,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/batch-transformations", response_model=BatchTransformationPage)
def list_batch_transformations(
    warehouse_id: int | None = None,
    batch_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_batch_transformations(
                warehouse_id=warehouse_id,
                batch_id=batch_id,
                limit=safe_limit,
                offset=safe_offset,
            ),
            "total": service.count_batch_transformations(
                warehouse_id=warehouse_id,
                batch_id=batch_id,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.post("/stock-documents/{document_id}/post", response_model=StockDocumentDetail)
async def post_stock_document(
    document_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        document_for_scope = service.get_stock_document(document_id)
        require_stock_access(actor_ctx, Permission.DOCUMENT_POST, document_for_scope["warehouse_id"])
        document, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/stock-documents/{document_id}/post",
            payload={"document_id": document_id},
            response_status=status.HTTP_200_OK,
            resource_type="stock_document",
            operation=lambda: service.post_stock_document(document_id, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.document.posted",
                {
                    "id": document["id"],
                    "document_type": document["document_type"],
                    "warehouse_id": document["warehouse_id"],
                },
            )
            await publish_event(
                "stock.balance.updated",
                {"warehouse_id": document["warehouse_id"], "document_id": document["id"]},
            )
            for line in document["lines"]:
                if line.get("target_warehouse_id") is not None:
                    await publish_event(
                        "stock.balance.updated",
                        {
                            "warehouse_id": line["target_warehouse_id"],
                            "document_id": document["id"],
                            "batch_id": line["batch_id"],
                        },
                    )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.post("/stock-documents/{document_id}/approve", response_model=StockDocumentDetail)
def approve_stock_document(
    document_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        document_for_scope = service.get_stock_document(document_id)
        require_stock_access(actor_ctx, Permission.DOCUMENT_POST, document_for_scope["warehouse_id"])
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/stock-documents/{document_id}/approve",
            payload={"document_id": document_id},
            response_status=status.HTTP_200_OK,
            resource_type="stock_document",
            operation=lambda: service.approve_stock_document(document_id, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.post("/stock-documents/{document_id}/cancel", response_model=StockDocumentDetail)
def cancel_stock_document(
    document_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        document_for_scope = service.get_stock_document(document_id)
        require_stock_access(actor_ctx, Permission.DOCUMENT_POST, document_for_scope["warehouse_id"])
        document, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/stock-documents/{document_id}/cancel",
            payload={"document_id": document_id},
            response_status=status.HTTP_200_OK,
            resource_type="stock_document",
            operation=lambda: service.cancel_stock_document(document_id, actor_id),
        )
        return document
    except Exception as error:
        raise map_error(error) from error


@router.patch("/batches/{batch_id}/status", response_model=Batch)
async def update_batch_status(
    batch_id: int,
    data: BatchStatusUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        warehouse_ids = service.get_batch_warehouse_ids(batch_id)
        for warehouse_id in warehouse_ids:
            require_stock_access(actor_ctx, Permission.STOCK_RECEIVE, warehouse_id)
        batch, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="PATCH",
            path=f"/api/v1/batches/{batch_id}/status",
            payload={"batch_id": batch_id, "status": data.status, "reason": data.reason},
            response_status=status.HTTP_200_OK,
            resource_type="batch",
            operation=lambda: service.update_batch_status(
                batch_id, data.status, data.reason, actor_id
            ),
        )
        if not replayed:
            for warehouse_id in warehouse_ids:
                await publish_event(
                    "batch.status.updated",
                    {"batch_id": batch_id, "warehouse_id": warehouse_id, "status": batch["status"]},
                )
        return batch
    except Exception as error:
        raise map_error(error) from error


@router.get("/quarantine-reviews", response_model=QuarantineReviewPage)
def list_quarantine_reviews(
    warehouse_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_quarantine_reviews(
                warehouse_id=warehouse_id,
                status=status,
                limit=safe_limit,
                offset=safe_offset,
            ),
            "total": service.count_quarantine_reviews(
                warehouse_id=warehouse_id,
                status=status,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/quarantine-reviews/{review_id}", response_model=QuarantineReview)
def get_quarantine_review(
    review_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        review = service.get_quarantine_review(review_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, review["warehouse_id"])
        return review
    except Exception as error:
        raise map_error(error) from error


@router.get("/quarantine-reviews/{review_id}/protocol", response_model=QuarantineReviewProtocol)
def get_quarantine_review_protocol(
    review_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        protocol = service.get_quarantine_review_protocol(review_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, protocol["warehouse_id"])
        return protocol
    except Exception as error:
        raise map_error(error) from error


@router.patch("/quarantine-reviews/{review_id}", response_model=QuarantineReview)
async def update_quarantine_review(
    review_id: int,
    data: QuarantineReviewUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        review = service.get_quarantine_review(review_id)
        require_stock_access(actor_ctx, Permission.STOCK_RECEIVE, review["warehouse_id"])
        updated = service.update_quarantine_review(review_id, data, actor_id)
        await publish_event(
            "batch.status.updated",
            {
                "batch_id": updated["batch_id"],
                "warehouse_id": updated["warehouse_id"],
                "quarantine_review_status": updated["status"],
            },
        )
        return updated
    except Exception as error:
        raise map_error(error) from error


@router.post("/write-offs", status_code=status.HTTP_201_CREATED, response_model=StockMovement)
async def write_off(
    data: WriteOffCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_WRITEOFF, data.warehouse_id)
        movement, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/write-offs",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_movement",
            operation=lambda: service.write_off(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.warehouse_id},
            )
        return movement
    except Exception as error:
        raise map_error(error) from error


@router.post("/write-offs/fefo", status_code=status.HTTP_201_CREATED, response_model=FefoWriteOffResult)
async def write_off_fefo(
    data: WriteOffFefoCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_WRITEOFF, data.warehouse_id)
        result, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/write-offs/fefo",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="stock_movement",
            operation=lambda: service.write_off_fefo(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.balance.updated",
                {"product_id": data.product_id, "warehouse_id": data.warehouse_id},
            )
        return result
    except Exception as error:
        raise map_error(error) from error


@router.get("/stock-movements", response_model=StockMovementPage)
def list_stock_movements(
    batch_id: int | None = None,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        items = service.list_stock_movements(
            batch_id=batch_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            limit=safe_limit,
            offset=safe_offset,
        )
        return {
            "items": items,
            "total": service.count_stock_movements(
                batch_id=batch_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/controlled-substances/ledger", response_model=ControlledSubstanceLedgerPage)
def list_controlled_substance_ledger(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    batch_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.AUDIT_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_controlled_substance_ledger(
                warehouse_id=warehouse_id,
                product_id=product_id,
                batch_id=batch_id,
                limit=safe_limit,
                offset=safe_offset,
            ),
            "total": service.count_controlled_substance_ledger(
                warehouse_id=warehouse_id,
                product_id=product_id,
                batch_id=batch_id,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/controlled-substances/ledger/export", response_model=ControlledSubstanceLedgerExport)
def export_controlled_substance_ledger(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    batch_id: int | None = None,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.AUDIT_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        return service.export_controlled_substance_ledger(
            warehouse_id=warehouse_id,
            product_id=product_id,
            batch_id=batch_id,
        )
    except Exception as error:
        raise map_error(error) from error


@router.post("/transfers", status_code=status.HTTP_201_CREATED, response_model=TransferResult)
async def transfer(
    data: TransferCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_TRANSFER, data.source_warehouse_id)
        require_stock_access(actor_ctx, Permission.STOCK_TRANSFER, data.target_warehouse_id)
        result, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/transfers",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="transfer",
            operation=lambda: service.transfer(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.transfer.posted",
                {
                    "batch_id": data.batch_id,
                    "source_warehouse_id": data.source_warehouse_id,
                    "target_warehouse_id": data.target_warehouse_id,
                },
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.source_warehouse_id},
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.target_warehouse_id},
            )
        return result
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/returns/from-department",
    status_code=status.HTTP_201_CREATED,
    response_model=TransferResult,
)
async def return_from_department(
    data: DepartmentReturnCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_TRANSFER, data.source_warehouse_id)
        require_stock_access(actor_ctx, Permission.STOCK_TRANSFER, data.target_warehouse_id)
        result, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/returns/from-department",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="return_from_department",
            operation=lambda: service.return_from_department(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.return.posted",
                {
                    "return_type": "from_department",
                    "batch_id": data.batch_id,
                    "source_warehouse_id": data.source_warehouse_id,
                    "target_warehouse_id": data.target_warehouse_id,
                },
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.source_warehouse_id},
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.target_warehouse_id},
            )
        return result
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/returns/to-supplier",
    status_code=status.HTTP_201_CREATED,
    response_model=SupplierReturnResult,
)
async def return_to_supplier(
    data: SupplierReturnCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_TRANSFER, data.warehouse_id)
        result, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/returns/to-supplier",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="return_to_supplier",
            operation=lambda: service.return_to_supplier(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "stock.return.posted",
                {
                    "return_type": "to_supplier",
                    "batch_id": data.batch_id,
                    "warehouse_id": data.warehouse_id,
                    "supplier_id": data.supplier_id,
                },
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.warehouse_id},
            )
        return result
    except Exception as error:
        raise map_error(error) from error


@router.post("/reservations", status_code=status.HTTP_201_CREATED, response_model=Reservation)
async def reserve(
    data: ReservationCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.STOCK_RESERVE, data.warehouse_id)
        reservation, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/reservations",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="reservation",
            operation=lambda: service.reserve(data, actor_id),
        )
        if not replayed:
            await publish_event(
                "reservation.created",
                {"batch_id": data.batch_id, "warehouse_id": data.warehouse_id, "id": reservation["id"]},
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": data.batch_id, "warehouse_id": data.warehouse_id},
            )
        return reservation
    except Exception as error:
        raise map_error(error) from error


@router.get("/reservations", response_model=list[Reservation])
def list_reservations(
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_RESERVE)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_reservations(warehouse_id, safe_limit, safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.post("/reservations/{reservation_id}/release", response_model=Reservation)
async def release_reservation(
    reservation_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        reservation_for_scope = service.get_reservation(reservation_id)
        require_stock_access(actor_ctx, Permission.STOCK_RESERVE, reservation_for_scope["warehouse_id"])
        reservation, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/reservations/{reservation_id}/release",
            payload={"reservation_id": reservation_id},
            response_status=status.HTTP_200_OK,
            resource_type="reservation",
            operation=lambda: service.release_reservation(reservation_id, actor_id),
        )
        if not replayed:
            await publish_event(
                "reservation.released",
                {
                    "id": reservation["id"],
                    "batch_id": reservation["batch_id"],
                    "warehouse_id": reservation["warehouse_id"],
                },
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": reservation["batch_id"], "warehouse_id": reservation["warehouse_id"]},
            )
        return reservation
    except Exception as error:
        raise map_error(error) from error


@router.post("/reservations/{reservation_id}/use", response_model=Reservation)
async def use_reservation(
    reservation_id: int,
    data: ReservationUseCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        reservation_for_scope = service.get_reservation(reservation_id)
        require_stock_access(
            actor_ctx, Permission.STOCK_WRITEOFF, reservation_for_scope["warehouse_id"]
        )
        reservation, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/reservations/{reservation_id}/use",
            payload={"reservation_id": reservation_id, "data": data},
            response_status=status.HTTP_200_OK,
            resource_type="reservation",
            operation=lambda: service.use_reservation(reservation_id, data, actor_id),
        )
        if not replayed:
            await publish_event(
                "reservation.used",
                {
                    "id": reservation["id"],
                    "batch_id": reservation["batch_id"],
                    "warehouse_id": reservation["warehouse_id"],
                },
            )
            await publish_event(
                "stock.balance.updated",
                {"batch_id": reservation["batch_id"], "warehouse_id": reservation["warehouse_id"]},
            )
        return reservation
    except Exception as error:
        raise map_error(error) from error


@router.post("/reservations/expire", response_model=list[Reservation])
async def expire_reservations(
    warehouse_id: int | None = None,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_RESERVE)
        require_warehouse_filter(actor_ctx, warehouse_id)
        reservations, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/reservations/expire",
            payload={"warehouse_id": warehouse_id},
            response_status=status.HTTP_200_OK,
            resource_type="reservation_expiration",
            operation=lambda: service.expire_reservations(
                actor_id=actor_id, warehouse_id=warehouse_id
            ),
        )
        if not replayed:
            for reservation in reservations:
                await publish_event(
                    "reservation.released",
                    {
                        "id": reservation["id"],
                        "batch_id": reservation["batch_id"],
                        "warehouse_id": reservation["warehouse_id"],
                    },
            )
        return reservations
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/inventory-sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=InventorySessionDetail,
)
def create_inventory_session(
    data: InventoryCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        require_stock_access(actor_ctx, Permission.INVENTORY_MANAGE, data.warehouse_id)
        session, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path="/api/v1/inventory-sessions",
            payload=data,
            response_status=status.HTTP_201_CREATED,
            resource_type="inventory_session",
            operation=lambda: service.create_inventory_session(data, actor_id),
        )
        return session
    except Exception as error:
        raise map_error(error) from error


@router.get("/inventory-sessions", response_model=list[InventorySessionDetail])
def list_inventory_sessions(
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return [
            service.get_inventory_session(session["id"])
            for session in service.list_inventory_sessions(warehouse_id, safe_limit, safe_offset)
        ]
    except Exception as error:
        raise map_error(error) from error


@router.get("/inventory-sessions/{session_id}", response_model=InventorySessionDetail)
def get_inventory_session(
    session_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        session = service.get_inventory_session(session_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, session["warehouse_id"])
        return session
    except Exception as error:
        raise map_error(error) from error


@router.get("/inventory-sessions/{session_id}/print-form", response_model=InventoryPrintForm)
def get_inventory_print_form(
    session_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        form = service.get_inventory_print_form(session_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, form["warehouse_id"])
        return form
    except Exception as error:
        raise map_error(error) from error


@router.patch("/inventory-sessions/{session_id}/lines/{line_id}", response_model=InventoryLine)
def update_inventory_line_count(
    session_id: int,
    line_id: int,
    data: InventoryLineCountUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
):
    try:
        session_for_scope = service.get_inventory_session(session_id)
        require_stock_access(actor_ctx, Permission.INVENTORY_MANAGE, session_for_scope["warehouse_id"])
        return service.update_inventory_line_count(session_id, line_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/inventory-sessions/{session_id}/post", response_model=InventorySessionDetail)
async def post_inventory_session(
    session_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        session_for_scope = service.get_inventory_session(session_id)
        require_stock_access(actor_ctx, Permission.INVENTORY_MANAGE, session_for_scope["warehouse_id"])
        session, replayed = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/inventory-sessions/{session_id}/post",
            payload={"session_id": session_id},
            response_status=status.HTTP_200_OK,
            resource_type="inventory_session",
            operation=lambda: service.post_inventory_session(session_id, actor_id),
        )
        if not replayed:
            await publish_event(
                "inventory.posted",
                {"id": session["id"], "warehouse_id": session["warehouse_id"]},
            )
            await publish_event(
                "stock.balance.updated",
                {"warehouse_id": session["warehouse_id"], "inventory_session_id": session["id"]},
            )
        return session
    except Exception as error:
        raise map_error(error) from error


@router.post("/inventory-sessions/{session_id}/cancel", response_model=InventorySessionDetail)
def cancel_inventory_session(
    session_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    idempotency_store: IdempotencyStore = Depends(get_idempotency_store),
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        session_for_scope = service.get_inventory_session(session_id)
        require_stock_access(actor_ctx, Permission.INVENTORY_MANAGE, session_for_scope["warehouse_id"])
        session, _ = run_idempotent(
            idempotency_key=idempotency_key,
            store=idempotency_store,
            actor_id=actor_id,
            method="POST",
            path=f"/api/v1/inventory-sessions/{session_id}/cancel",
            payload={"session_id": session_id},
            response_status=status.HTTP_200_OK,
            resource_type="inventory_session",
            operation=lambda: service.cancel_inventory_session(session_id, actor_id),
        )
        return session
    except Exception as error:
        raise map_error(error) from error


def pagination_meta(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 500)), max(0, offset)


@router.get("/balances", response_model=BalancePage)
def list_balances(
    product_id: int | None = None,
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_balances(product_id, warehouse_id, safe_limit, safe_offset),
            "total": service.count_balances(product_id, warehouse_id),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/analytics/abc-xyz", response_model=AbcXyzAnalysis)
def abc_xyz_analysis(
    warehouse_id: int | None = None,
    days: int = 90,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        return service.abc_xyz_analysis(analysis_days=days, warehouse_id=warehouse_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/analytics/abc-xyz/runs", response_model=AbcXyzRunDetail)
def create_abc_xyz_run(
    warehouse_id: int | None = None,
    days: int = 90,
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.DOCUMENT_CREATE)
        require_warehouse_filter(actor_ctx, warehouse_id)
        return service.save_abc_xyz_analysis_snapshot(
            analysis_days=days,
            warehouse_id=warehouse_id,
            actor_id=actor_id,
            source="manual",
        )
    except Exception as error:
        raise map_error(error) from error


@router.get("/analytics/abc-xyz/history", response_model=AbcXyzRunPage)
def list_abc_xyz_runs(
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_abc_xyz_runs(
                warehouse_id=warehouse_id,
                limit=safe_limit,
                offset=safe_offset,
            ),
            "total": service.count_abc_xyz_runs(warehouse_id=warehouse_id),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/analytics/abc-xyz/history/{run_id}", response_model=AbcXyzRunDetail)
def get_abc_xyz_run(
    run_id: int,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        run = service.get_abc_xyz_run(run_id)
        require_warehouse_filter(actor_ctx, run["warehouse_id"])
        return run
    except Exception as error:
        raise map_error(error) from error


@router.post("/purchase-requests/generate", response_model=list[PurchaseRequest])
def generate_purchase_requests(
    warehouse_id: int,
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, warehouse_id)
        return service.generate_purchase_requests(warehouse_id=warehouse_id, actor_id=actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/purchase-requests/generate-auto", response_model=list[PurchaseRequest])
def generate_purchase_requests_auto(
    warehouse_id: int,
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    service: WarehouseService = Depends(get_warehouse_service),
):
    return generate_purchase_requests(
        warehouse_id=warehouse_id,
        actor_ctx=actor_ctx,
        actor_id=actor_id,
        service=service,
    )


@router.post("/purchase-requests", status_code=status.HTTP_201_CREATED, response_model=PurchaseRequest)
def create_purchase_request(
    payload: PurchaseRequestCreate,
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, payload.warehouse_id)
        return service.create_purchase_request(payload, actor_id=actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/purchase-requests", response_model=list[PurchaseRequest])
def list_purchase_requests(
    warehouse_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_purchase_requests(
            warehouse_id=warehouse_id,
            status=status,
            limit=safe_limit,
            offset=safe_offset,
        )
    except Exception as error:
        raise map_error(error) from error


@router.patch("/purchase-requests/{request_id}", response_model=PurchaseRequest)
def update_purchase_request_status(
    request_id: int,
    payload: PurchaseRequestStatusUpdate,
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        current = service.get_purchase_request(request_id)
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, current["warehouse_id"])
        return service.update_purchase_request_status(request_id, payload, actor_id=actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/supplier/purchase-requests", response_model=list[PurchaseRequest])
def list_supplier_purchase_requests(
    status: str | None = "draft",
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_supplier_purchase_requests(
            actor_id=actor_id,
            status=status,
            limit=safe_limit,
            offset=safe_offset,
        )
    except Exception as error:
        raise map_error(error) from error


@router.post(
    "/supplier/purchase-requests/{request_id}/offers",
    status_code=status.HTTP_201_CREATED,
    response_model=SupplierOffer,
)
def create_supplier_offer(
    request_id: int,
    payload: SupplierOfferCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.create_supplier_offer(request_id, payload, actor_id=actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/supplier/offers", response_model=list[SupplierOffer])
def list_my_supplier_offers(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_supplier_offers(actor_id, status, safe_limit, safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.patch("/supplier/offers/{offer_id}/withdraw", response_model=SupplierOffer)
def withdraw_my_supplier_offer(
    offer_id: int,
    payload: dict[str, str | None] | None = None,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.withdraw_supplier_offer(
            offer_id,
            actor_id=actor_id,
            reason=(payload or {}).get("reason"),
        )
    except Exception as error:
        raise map_error(error) from error


@router.get("/purchase-requests/{request_id}/offers", response_model=list[SupplierOffer])
def list_purchase_request_offers(
    request_id: int,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        current = service.get_purchase_request(request_id)
        require_stock_access(actor_ctx, Permission.STOCK_READ, current["warehouse_id"])
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_purchase_request_offers(request_id, status, safe_limit, safe_offset)
    except Exception as error:
        raise map_error(error) from error


@router.get("/supplier-offers", response_model=list[SupplierOffer])
def list_supplier_offers_for_admin(
    warehouse_id: int | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    product_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return service.list_supplier_offers_for_admin(
            warehouse_id=warehouse_id,
            status=status,
            supplier_id=supplier_id,
            product_id=product_id,
            limit=safe_limit,
            offset=safe_offset,
        )
    except Exception as error:
        raise map_error(error) from error


@router.patch("/supplier-offers/{offer_id}/review", response_model=SupplierOffer)
def review_supplier_offer(
    offer_id: int,
    payload: SupplierOfferReview,
    actor_ctx: ActorContext = Depends(get_actor_context),
    actor_id: str = Depends(actor),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        offer = service.get_supplier_offer(offer_id)
        require_stock_access(actor_ctx, Permission.DOCUMENT_CREATE, offer["warehouse_id"])
        return service.review_supplier_offer(offer_id, payload, reviewer_id=actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/supplier/catalog", response_model=SupplierCatalogPage)
def list_my_catalog(
    type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_supplier_catalog(actor_id, type, safe_limit, safe_offset),
            "total": service.count_supplier_catalog(actor_id, type),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.post("/supplier/catalog", status_code=status.HTTP_201_CREATED, response_model=SupplierCatalog)
def create_catalog_item(
    data: SupplierCatalogCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.create_catalog_item(data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.patch("/supplier/catalog/{item_id}", response_model=SupplierCatalog)
def update_catalog_item(
    item_id: int,
    data: SupplierCatalogUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.update_catalog_item(item_id, data, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.delete("/supplier/catalog/{item_id}", response_model=SupplierCatalog)
def delete_catalog_item(
    item_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        return service.delete_catalog_item(item_id, actor_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/supplier/catalog/{item_id}/image", response_model=SupplierCatalog)
def upload_catalog_image(
    item_id: int,
    file: UploadFile = File(...),
    service: WarehouseService = Depends(get_warehouse_service),
    actor_id: str = Depends(actor),
):
    try:
        settings = get_settings()
        if not settings.telegram_bot_token or not settings.telegram_upload_chat_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "not_configured", "message": "Image upload is not configured", "details": {}},
            )
        content = file.file.read()
        filename = file.filename or "photo.jpg"
        boundary = b"----FormBoundary"
        body = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            + settings.telegram_upload_chat_id.encode() + b"\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="photo"; filename="' + filename.encode() + b'"\r\n'
            b"Content-Type: " + (file.content_type or "image/jpeg").encode() + b"\r\n\r\n"
            + content + b"\r\n"
            b"--" + boundary + b"--\r\n"
        )
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
            method="POST",
        )
        import json as _json
        with urllib.request.urlopen(req, timeout=30) as resp:
            tg_data = _json.loads(resp.read())
        if not tg_data.get("ok"):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "upload_failed", "message": "Telegram upload failed", "details": tg_data},
            )
        photos = tg_data["result"]["photo"]
        file_id = max(photos, key=lambda p: p.get("file_size", 0))["file_id"]
        return service.set_catalog_item_image(item_id, actor_id, file_id)
    except HTTPException:
        raise
    except Exception as error:
        raise map_error(error) from error


@router.get("/catalog/{item_id}/image")
def get_catalog_image(
    item_id: int,
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        settings = get_settings()
        if not settings.telegram_bot_token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        connection = service.database.connect()
        try:
            row = connection.execute(
                "SELECT image_file_id FROM supplier_catalog WHERE id = ? AND is_active = 1",
                (item_id,),
            ).fetchone()
        finally:
            service._close_connection(connection)
        if not row or not row["image_file_id"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No image")
        file_id = row["image_file_id"]
        import json as _json
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getFile?file_id={file_id}"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = _json.loads(resp.read())
        file_path = info["result"]["file_path"]
        img_url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
        with urllib.request.urlopen(img_url, timeout=30) as img_resp:
            content = img_resp.read()
            content_type = img_resp.headers.get("Content-Type", "image/jpeg")
        return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})
    except HTTPException:
        raise
    except Exception as error:
        raise map_error(error) from error


@router.get("/marketplace", response_model=SupplierCatalogPage)
def list_marketplace(
    type: str | None = None,
    service_category: str | None = None,
    supplier_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_marketplace(type, service_category, supplier_id, q, safe_limit, safe_offset),
            "total": service.count_marketplace(type, service_category, supplier_id, q),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.post("/notifications/generate-low-stock", response_model=list[Notification])
def generate_low_stock_notifications(
    warehouse_id: int | None = None,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.NOTIFICATIONS_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        return service.generate_low_stock_notifications(warehouse_id=warehouse_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/notifications/generate-expiry", response_model=list[Notification])
def generate_expiry_notifications(
    warehouse_id: int | None = None,
    days: int = 30,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.NOTIFICATIONS_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        return service.generate_expiry_notifications(days=days, warehouse_id=warehouse_id)
    except Exception as error:
        raise map_error(error) from error


@router.post("/notifications/generate-quarantine", response_model=list[Notification])
def generate_quarantine_notifications(
    warehouse_id: int | None = None,
    days: int = 3,
    service: WarehouseService = Depends(get_warehouse_service),
    actor_ctx: ActorContext = Depends(get_actor_context),
):
    try:
        require_permission(actor_ctx, Permission.NOTIFICATIONS_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        return service.generate_quarantine_notifications(days=days, warehouse_id=warehouse_id)
    except Exception as error:
        raise map_error(error) from error


@router.get("/notifications", response_model=NotificationPage)
def list_notifications(
    unread_only: bool = False,
    warehouse_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.NOTIFICATIONS_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_notifications(
                unread_only, safe_limit, safe_offset, warehouse_id=warehouse_id
            ),
            "total": service.count_notifications(unread_only, warehouse_id=warehouse_id),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.get("/audit-log", response_model=AuditLogPage)
def list_audit_log(
    entity_type: str | None = None,
    warehouse_id: int | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.AUDIT_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
        safe_limit, safe_offset = pagination_meta(limit, offset)
        return {
            "items": service.list_audit_log(
                entity_type,
                safe_limit,
                safe_offset,
                warehouse_id=warehouse_id,
                actor_id=actor_id,
                action=action,
            ),
            "total": service.count_audit_log(
                entity_type,
                warehouse_id=warehouse_id,
                actor_id=actor_id,
                action=action,
            ),
            "limit": safe_limit,
            "offset": safe_offset,
        }
    except Exception as error:
        raise map_error(error) from error


@router.patch("/notifications/{notification_id}/read", response_model=Notification)
def mark_notification_read(
    notification_id: int,
    data: NotificationReadUpdate,
    actor_ctx: ActorContext = Depends(get_actor_context),
    service: WarehouseService = Depends(get_warehouse_service),
):
    try:
        require_permission(actor_ctx, Permission.NOTIFICATIONS_READ)
        notification = service.get_notification(notification_id)
        require_warehouse_filter(actor_ctx, notification["warehouse_id"])
        return service.mark_notification_read(notification_id, data.is_read)
    except Exception as error:
        raise map_error(error) from error


@router.websocket("/ws/balances")
async def balances_ws(
    websocket: WebSocket, warehouse_id: int | None = None, access_token: str | None = None
):
    try:
        settings = get_settings()
        if not settings.dev_auth_enabled:
            token = access_token
            authorization = websocket.headers.get("authorization")
            if authorization:
                scheme, _, raw_token = authorization.partition(" ")
                if scheme.lower() != "bearer" or not raw_token.strip():
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                token = raw_token.strip()
            if not token or not settings.jwt_hmac_secret:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            actor_ctx = actor_from_bearer_token(
                token,
                secret=settings.jwt_hmac_secret,
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                leeway_seconds=settings.jwt_clock_skew_seconds,
            )
        else:
            actor_ctx = actor_from_headers(
                actor_id=websocket.headers.get("x-actor-id", "system"),
                roles_header=websocket.headers.get("x-actor-roles"),
                warehouse_ids_header=websocket.headers.get("x-actor-warehouse-ids"),
                department=websocket.headers.get("x-actor-department"),
                allow_dev_default=settings.dev_auth_enabled,
            )
        require_permission(actor_ctx, Permission.STOCK_READ)
        require_warehouse_filter(actor_ctx, warehouse_id)
    except (AuthenticationError, PermissionDeniedError, ValidationError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    warehouse_scope = None
    if Role.WAREHOUSE_MANAGER not in actor_ctx.roles:
        warehouse_scope = frozenset({warehouse_id}) if warehouse_id is not None else actor_ctx.warehouse_ids

    await manager.connect(websocket, warehouse_scope=warehouse_scope)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
