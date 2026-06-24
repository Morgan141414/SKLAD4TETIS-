from enum import StrEnum


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RECEIPT = "receipt"
    WRITE_OFF = "write_off"
    RESERVE = "reserve"
    RELEASE_RESERVE = "release_reserve"
    TRANSFER = "transfer"
    RETURN = "return"
    REPACK = "repack"
    RECALL = "recall"
    INVENTORY_LOCK = "inventory_lock"
    INVENTORY_POST = "inventory_post"
    INVENTORY_CANCEL = "inventory_cancel"


class BatchStatus(StrEnum):
    AVAILABLE = "available"
    QUARANTINE = "quarantine"
    BLOCKED = "blocked"


class QuarantineReviewStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class MovementType(StrEnum):
    RECEIPT = "receipt"
    WRITE_OFF = "write_off"
    RESERVE = "reserve"
    RELEASE_RESERVE = "release_reserve"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    RETURN_TO_SUPPLIER = "return_to_supplier"
    REPACK_OUT = "repack_out"
    REPACK_IN = "repack_in"


class StockDocumentStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    POSTED = "posted"
    CANCELLED = "cancelled"


class StockDocumentType(StrEnum):
    RECEIPT = "receipt"
    WRITE_OFF = "write_off"
    TRANSFER = "transfer"
    DEPARTMENT_RETURN = "department_return"
    SUPPLIER_RETURN = "supplier_return"
    REPACK = "repack"


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    USED = "used"
    RELEASED = "released"


class InventoryStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    POSTED = "posted"
    CANCELLED = "cancelled"
