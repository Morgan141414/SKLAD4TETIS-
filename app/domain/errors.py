class SkladError(Exception):
    """Base business error."""


class NotFoundError(SkladError):
    pass


class ValidationError(SkladError):
    pass


class AuthenticationError(ValidationError):
    pass


class PermissionDeniedError(ValidationError):
    pass


class ConflictError(SkladError):
    pass


class IdempotencyConflictError(ConflictError, ValidationError):
    pass


class InsufficientStockError(SkladError):
    pass


class InventoryLockedError(SkladError):
    pass


class BatchUnavailableError(SkladError):
    pass
