# Service Decomposition Plan

Цель: безопасно разделить большой `WarehouseService`, не ломая текущие API imports и тесты.

## Главный принцип

Не переименовывать `app/services/warehouse.py` сразу. Этот файл должен остаться фасадом, потому что его импортируют API и тесты:

```python
from app.services.warehouse import WarehouseService
```

Реализацию нужно выносить постепенно в соседний package, например `app/services/warehouse_parts/`.

## Целевые части

- `catalog.py`: категории, поставщики, склады, товары.
- `stock.py`: приход, списание, FEFO, статусы партий, остатки.
- `documents.py`: документы прихода/списания и posting.
- `transfers.py`: внутренние перемещения.
- `returns.py`: возвраты.
- `reservations.py`: резервы, снятие, истечение.
- `inventory.py`: инвентаризация и inventory lock.
- `notifications.py`: уведомления.
- `audit.py`: audit writer and audit reads.
- `primitives.py`: `_require`, `_get_by_id`, `_balance_for_update`, `_movement`, common guards.

## Порядок

1. Добавить characterization tests.
2. Вынести audit/primitives без изменения публичного фасада.
3. Вынести stock operations.
4. Вынести documents, transfers, returns.
5. Вынести reservations, inventory, notifications.
6. Только после этого постепенно переводить routes на новые сервисы.

## Риски

- Нельзя открывать вложенные транзакции внутри сценариев.
- Нельзя дублировать `_apply_writeoff_line`, `_apply_transfer`, `_apply_receipt_line`.
- Inventory lock должен оставаться единым guard.
- Audit payload serialization должна быть общей.
- Posting документов должен продолжать использовать stock primitives, а не копировать логику.

