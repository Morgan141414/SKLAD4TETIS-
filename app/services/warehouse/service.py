from __future__ import annotations

from app.services.warehouse.admin import AdminMixin
from app.services.warehouse.catalog_catalog import CatalogCatalogMixin
from app.services.warehouse.ledger_helpers import LedgerHelpersMixin
from app.services.warehouse.marketplace import MarketplaceMixin
from app.services.warehouse.procurement_analytics import ProcurementAnalyticsMixin
from app.services.warehouse.reports import ReportsMixin
from app.services.warehouse.stock_documents import StockDocumentsMixin
from app.services.warehouse.warehouse_assets import WarehouseAssetsMixin


class WarehouseService(
CatalogCatalogMixin,
MarketplaceMixin,
WarehouseAssetsMixin,
StockDocumentsMixin,
ProcurementAnalyticsMixin,
ReportsMixin,
LedgerHelpersMixin,
AdminMixin,
):
    pass
