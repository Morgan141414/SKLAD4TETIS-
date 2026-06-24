from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import WebSocket
else:
    WebSocket = Any


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._warehouse_scopes: dict[WebSocket, frozenset[int] | None] = {}

    async def connect(
        self, websocket: WebSocket, warehouse_scope: frozenset[int] | None = None
    ) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        self._warehouse_scopes[websocket] = warehouse_scope

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        self._warehouse_scopes.pop(websocket, None)

    async def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"event": event, "payload": payload}, default=str)
        stale: list[WebSocket] = []
        for connection in self.active_connections:
            if not self._can_receive(connection, payload):
                continue
            try:
                await connection.send_text(message)
            except RuntimeError:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)

    def _can_receive(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        scope = self._warehouse_scopes.get(websocket)
        if scope is None:
            return True
        payload_warehouse_ids = self._payload_warehouse_ids(payload)
        if not payload_warehouse_ids:
            return False
        return bool(scope.intersection(payload_warehouse_ids))

    def _payload_warehouse_ids(self, payload: dict[str, Any]) -> set[int]:
        warehouse_ids: set[int] = set()
        for key in ("warehouse_id", "source_warehouse_id", "target_warehouse_id"):
            value = payload.get(key)
            if isinstance(value, int):
                warehouse_ids.add(value)
        return warehouse_ids


manager = ConnectionManager()
