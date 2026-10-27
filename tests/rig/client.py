"""A small Home Assistant client for rig tests: WebSocket for service calls and state events, REST for reads."""

import asyncio
import contextlib
import itertools
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import aiohttp


class HAError(Exception):
    """A failed WebSocket command, carrying HA's error code and translation key."""

    def __init__(self, error: dict):
        super().__init__(error.get("message", ""))
        self.code: str | None = error.get("code")
        self.translation_key: str | None = error.get("translation_key")
        self.translation_placeholders: dict = error.get("translation_placeholders") or {}


class HAClient:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._mqtt: dict[int, asyncio.Queue[str]] = {}  # MQTT subscriptions by WebSocket id
        self._states: dict[str, dict] = {}
        self._changed = asyncio.Condition()
        self._reader: asyncio.Task | None = None

    async def connect(self) -> None:
        # The system resolver, not aiohttp's default aiodns: only the system one resolves mDNS (.local) names.
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
        self._session = aiohttp.ClientSession(connector=connector, headers={"Authorization": f"Bearer {self.token}"})
        try:
            self._ws = await self._session.ws_connect(f"{self.url}/api/websocket")
        except aiohttp.ClientError:
            await self._session.close()
            raise
        if (await self._ws.receive_json())["type"] != "auth_required":
            raise RuntimeError("unexpected WebSocket greeting")
        await self._ws.send_json({"type": "auth", "access_token": self.token})
        if (reply := await self._ws.receive_json())["type"] != "auth_ok":
            raise RuntimeError(f"WebSocket auth failed: {reply.get('message')}")
        self._reader = asyncio.create_task(self._read())
        await self.command({"type": "subscribe_events", "event_type": "state_changed"})

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
        if self._ws is not None:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()

    async def _read(self) -> None:
        async for message in self._ws:
            data = message.json()
            if data["type"] == "result":
                if (future := self._pending.pop(data["id"], None)) is not None and not future.done():
                    future.set_result(data)
            elif data["type"] == "event" and (queue := self._mqtt.get(data["id"])) is not None:
                queue.put_nowait(data["event"]["payload"])
            elif data["type"] == "event":
                event = data["event"]["data"]
                async with self._changed:
                    self._states[event["entity_id"]] = event["new_state"]
                    self._changed.notify_all()

    async def command(self, payload: dict, msg_id: int | None = None) -> Any:
        msg_id = next(self._ids) if msg_id is None else msg_id
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        await self._ws.send_json({"id": msg_id, **payload})
        reply = await asyncio.wait_for(future, timeout=30)
        if not reply["success"]:
            raise HAError(reply["error"])
        return reply["result"]

    async def call_service(
        self, domain: str, service: str, data: dict | None = None, return_response: bool = False
    ) -> dict | None:
        """Call a service; entity_id goes in data. Returns the service response when asked for one."""
        data = dict(data or {})
        payload = {"type": "call_service", "domain": domain, "service": service, "service_data": data}
        if return_response:
            payload["return_response"] = True
        result = await self.command(payload)
        return result.get("response") if return_response else None

    async def get_state(self, entity_id: str) -> dict | None:
        async with self._session.get(f"{self.url}/api/states/{entity_id}") as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            state = await response.json()
        async with self._changed:
            # An event that landed while the request was in flight is newer; keep it.
            cached = self._states.get(entity_id)
            if cached is not None and cached["last_updated"] > state["last_updated"]:
                return cached
            self._states[entity_id] = state
        return state

    async def wait_for(self, entity_id: str, predicate: Callable[[dict | None], bool], timeout: float) -> dict | None:
        """The entity's state once predicate holds; raises TimeoutError otherwise. Checks the current state first."""
        current = await self.get_state(entity_id)
        if predicate(current):
            return current
        async with asyncio.timeout(timeout), self._changed:
            await self._changed.wait_for(lambda: predicate(self._states.get(entity_id)))
            return self._states.get(entity_id)

    @contextlib.asynccontextmanager
    async def _mqtt_messages(self, topic: str) -> AsyncIterator[asyncio.Queue[str]]:
        """Payloads on an MQTT topic while the block runs, a retained one first. Needs an admin token."""
        msg_id = next(self._ids)
        self._mqtt[msg_id] = asyncio.Queue()
        try:
            await self.command({"type": "mqtt/subscribe", "topic": topic}, msg_id)
            yield self._mqtt[msg_id]
        finally:
            del self._mqtt[msg_id]
            with contextlib.suppress(HAError):
                await self.command({"type": "unsubscribe_events", "subscription": msg_id})

    async def z2m_device_options(self, ieee: str) -> dict:
        """A Zigbee2MQTT device's options, from Z2M's retained bridge/info."""
        async with self._mqtt_messages("zigbee2mqtt/bridge/info") as messages:
            info = json.loads(await asyncio.wait_for(messages.get(), timeout=5))
        return info["config"]["devices"].get(ieee, {})

    async def set_z2m_device_options(self, ieee: str, options: dict) -> None:
        """Set Zigbee2MQTT device options and wait for Z2M's ok; raises RuntimeError on anything else."""
        transaction = uuid.uuid4().hex
        async with self._mqtt_messages("zigbee2mqtt/bridge/response/device/options") as replies:
            payload = {"id": ieee, "options": options, "transaction": transaction}
            await self.call_service(
                "mqtt",
                "publish",
                {"topic": "zigbee2mqtt/bridge/request/device/options", "payload": json.dumps(payload)},
            )
            async with asyncio.timeout(10):
                while (reply := json.loads(await replies.get())).get("transaction") != transaction:
                    pass
        if reply.get("status") != "ok":
            raise RuntimeError(f"Zigbee2MQTT refused {options} for {ieee}: {reply.get('error')}")
