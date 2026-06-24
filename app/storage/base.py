from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol


class WarehouseConnection(Protocol):
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        ...

    def close(self) -> None:
        ...


class WarehouseDatabase(Protocol):
    def connect(self) -> WarehouseConnection:
        ...

    def transaction(self) -> Iterator[WarehouseConnection]:
        ...

