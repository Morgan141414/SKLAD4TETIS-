import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor

from app.realtime.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, message: str) -> None:
        self.messages.append(message)


def run(coro):
    # Runs in a dedicated thread so a leaked event loop on the main thread
    # (left running by other async test infra in the full suite) can not
    # collide with asyncio.run()s no-running-loop requirement.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


class ConnectionManagerTest(unittest.TestCase):
    def test_scoped_connection_receives_only_matching_warehouse_events(self) -> None:
        async def body():
            manager = ConnectionManager()
            warehouse_10 = FakeWebSocket()
            warehouse_20 = FakeWebSocket()
            await manager.connect(warehouse_10, warehouse_scope=frozenset({10}))
            await manager.connect(warehouse_20, warehouse_scope=frozenset({20}))
            await manager.broadcast("stock.balance.updated", {"warehouse_id": 10})
            self.assertEqual(len(warehouse_10.messages), 1)
            self.assertEqual(warehouse_20.messages, [])
        run(body())

    def test_global_connection_receives_all_warehouse_events(self) -> None:
        async def body():
            manager = ConnectionManager()
            global_connection = FakeWebSocket()
            scoped_connection = FakeWebSocket()
            await manager.connect(global_connection)
            await manager.connect(scoped_connection, warehouse_scope=frozenset({20}))
            await manager.broadcast("stock.balance.updated", {"warehouse_id": 10})
            self.assertEqual(len(global_connection.messages), 1)
            self.assertEqual(scoped_connection.messages, [])
        run(body())

    def test_transfer_event_is_delivered_to_source_or_target_scope(self) -> None:
        async def body():
            manager = ConnectionManager()
            source_connection = FakeWebSocket()
            unrelated_connection = FakeWebSocket()
            await manager.connect(source_connection, warehouse_scope=frozenset({10}))
            await manager.connect(unrelated_connection, warehouse_scope=frozenset({30}))
            await manager.broadcast(
                "stock.transfer.posted",
                {"source_warehouse_id": 10, "target_warehouse_id": 20},
            )
            self.assertEqual(len(source_connection.messages), 1)
            self.assertEqual(unrelated_connection.messages, [])
        run(body())

    def test_scoped_connection_does_not_receive_unscoped_events(self) -> None:
        async def body():
            manager = ConnectionManager()
            global_connection = FakeWebSocket()
            scoped_connection = FakeWebSocket()
            await manager.connect(global_connection)
            await manager.connect(scoped_connection, warehouse_scope=frozenset({10}))
            await manager.broadcast("system.notice", {"message": "maintenance"})
            self.assertEqual(len(global_connection.messages), 1)
            self.assertEqual(scoped_connection.messages, [])
        run(body())
