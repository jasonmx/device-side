"""Fabricate Zigbee2MQTT entities the way Z2M registers them via MQTT discovery, and a broker with Z2M behind it."""

import asyncio
import json
from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

IEEE = "0x00124b0012345678"
INFO = "zigbee2mqtt/bridge/info"
GROUPS = "zigbee2mqtt/bridge/groups"


def z2m_entry(hass: HomeAssistant) -> MockConfigEntry:
    """One loaded MQTT config entry for Z2M (all Z2M devices share a single entry)."""
    # Untitled, as HA names a device without one after its entry; Z2M names every device after its friendly name.
    entry = MockConfigEntry(domain="mqtt", title="")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def add_z2m_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    ieee: str = IEEE,
    state: str = "off",
    attributes: dict | None = None,
    manufacturer: str | None = None,
    name: str | None = None,
) -> str:
    """Register one Z2M device entity with the identifier Z2M writes via MQTT discovery.

    Each device has its own device-registry entry (keyed by ieee); all share one config entry.
    """
    domain, object_id = entity_id.split(".")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("mqtt", f"zigbee2mqtt_{ieee}")},
        manufacturer=manufacturer,
        name=name,
    )
    er.async_get(hass).async_get_or_create(
        domain,
        "mqtt",
        ieee,
        suggested_object_id=object_id,
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(entity_id, state, attributes or {})
    return entity_id


def add_z2m_group(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    group_id: int,
    base_topic: str = "zigbee2mqtt",
    state: str = "off",
    name: str | None = None,
) -> str:
    """Register one Z2M group entity with the identifier Z2M writes via MQTT discovery.

    Z2M encodes the base topic as character codes joined with no separator, then appends the
    group ID (getDevicePayload and getEncodedBaseTopic in lib/extension/homeassistant.ts).
    """
    encoded = "".join(str(ord(c)) for c in base_topic)
    return add_z2m_entity(hass, entry, entity_id, ieee=f"{encoded}_{group_id}", state=state, name=name)


class Broker:
    """MQTT as the adapters see it, and Z2M answering options requests and reads.

    Like HA's client, a subscription goes live only when its debounced batch reaches the broker (here, on the next
    loop turn), and a retained message is delivered then. A reply published before that is lost.
    """

    def __init__(self) -> None:
        self.retained: dict[str, object] = {}
        self.pending: list[tuple[str, object]] = []
        self.subscribers: dict[str, list] = {}
        self.topics: list[str] = []  # every topic ever subscribed
        self.published: list[dict] = []
        self.reply: dict | str | None = {"status": "ok"}  # merged with the transaction; a str is sent as is
        self.refused: set[str] = set()  # IDs whose options requests Z2M answers with an error
        # Each device's attributes by cluster, keyed by IEEE, with the friendly name its state is published under.
        self.devices: dict[str, tuple[str, dict[str, dict]]] = {}
        self.read_errors: dict[tuple[str, str], str] = {}  # (IEEE, cluster) -> the status Z2M logs for a failed read
        self.before_reply: list[dict] = []  # state payloads published ahead of each read's reply
        self.logs_before_reply: list[str] = []  # bridge/logging payloads published ahead of each read's reply
        self.states: dict[str, dict] = {}  # the state Z2M keeps for each device, keyed by IEEE, in every publish

    async def subscribe(self, hass, topic, msg_callback):
        self.topics.append(topic)
        if topic in {f"zigbee2mqtt/{name}" for name, _ in self.devices.values()}:
            # HA's light entity already subscribes to its state topic, so another subscription is live at once.
            self.subscribers.setdefault(topic, []).append(msg_callback)
            if topic in self.retained:
                message = SimpleNamespace(topic=topic, payload=json.dumps(self.retained[topic]), retain=True)
                asyncio.get_running_loop().call_soon(msg_callback, message)
            return lambda: self.subscribers[topic].remove(msg_callback)
        if not self.pending:
            asyncio.get_running_loop().call_soon(self.flush)
        self.pending.append((topic, msg_callback))

        def unsubscribe() -> None:
            if (topic, msg_callback) in self.pending:
                self.pending.remove((topic, msg_callback))
            else:
                self.subscribers[topic].remove(msg_callback)

        return unsubscribe

    def flush(self) -> None:
        batch, self.pending = self.pending, []
        for topic, msg_callback in batch:
            self.subscribers.setdefault(topic, []).append(msg_callback)
        for topic, msg_callback in batch:
            if topic in self.retained:
                msg_callback(SimpleNamespace(topic=topic, payload=json.dumps(self.retained[topic]), retain=True))

    def deliver(self, topic: str, payload: str) -> None:
        for msg_callback in list(self.subscribers.get(topic, [])):
            msg_callback(SimpleNamespace(topic=topic, payload=payload, retain=False))

    def listening(self, topic: str) -> bool:
        return bool(self.subscribers.get(topic)) or any(t == topic for t, _ in self.pending)

    @callback
    def publish(self, service: ServiceCall) -> None:
        topic, payload = service.data["topic"], json.loads(service.data["payload"])
        self.published.append({"topic": topic, "payload": payload})
        if "read" in payload:
            self._read(topic.split("/")[1], payload["read"])
        elif topic.startswith("zigbee2mqtt/bridge/request/") and self.reply is not None:
            response = topic.replace("/request/", "/response/")
            self.deliver(response, json.dumps({"transaction": "someone else's", "status": "error"}))
            if isinstance(self.reply, str):
                self.deliver(response, self.reply)
            else:
                reply = {"status": "error", "error": "refused"} if payload.get("id") in self.refused else self.reply
                self.deliver(response, json.dumps({**reply, "transaction": payload["transaction"]}))

    def _read(self, ieee: str, read: dict) -> None:
        """Z2M's answer to a generic read: the reply in the device's state, or a line on its log."""
        if ieee not in self.devices:
            return
        name, clusters = self.devices[ieee]
        cluster = read["cluster"]
        if status := self.read_errors.get((ieee, cluster)):
            message = f"Publish 'set' 'read' to '{name}' failed: ZCL command {ieee}/11 {cluster}.read() failed"
            message += f" ({status})"
            self.deliver("zigbee2mqtt/bridge/logging", json.dumps({"level": "error", "message": message}))
            return
        for line in self.logs_before_reply:
            self.deliver("zigbee2mqtt/bridge/logging", line)
        for payload in self.before_reply:
            self.deliver(f"zigbee2mqtt/{name}", json.dumps(payload))
        reply = {attribute: clusters[cluster][attribute] for attribute in read["attributes"]}
        state = self.states.setdefault(ieee, {"state": "ON"})
        if "currentLevel" in reply:
            state["brightness"] = reply["currentLevel"]
        self.deliver(f"zigbee2mqtt/{name}", json.dumps({**state, read["state_property"]: reply}))

    def reads(self) -> list[tuple[str, dict]]:
        """Each read sent, as (topic, read payload)."""
        return [(p["topic"], p["payload"]["read"]) for p in self.published if "read" in p["payload"]]

    def requests(self) -> list[dict]:
        return [p for p in self.published if p["topic"].startswith("zigbee2mqtt/bridge/request/")]

    def timers(self) -> list[dict]:
        return [p for p in self.published if p["payload"].get("on_time") is not None]
