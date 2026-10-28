"""Zigbee2MQTT's bridge: its groups, device features and entity options from retained topics, and options requests."""

import asyncio
import json
from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .addressing import bridge_topic

# Retained topics arrive once HA's debounced subscribe reaches the broker; the reply takes one settings write.
_RETAINED_TIMEOUT_S = 2.0
_REPLY_TIMEOUT_S = 5.0


async def group_members(hass: HomeAssistant, group: str) -> list[str]:
    """The IEEE addresses of a Z2M group's members, from bridge/groups; none for a group it doesn't list."""
    payload: asyncio.Future[str] = hass.loop.create_future()
    unsubscribe = await mqtt.async_subscribe(hass, bridge_topic("groups"), first_payload(payload))
    try:
        groups = json.loads(await wait(payload, _RETAINED_TIMEOUT_S, "no bridge/groups from Zigbee2MQTT"))
    finally:
        unsubscribe()
    members = next((g.get("members", []) for g in groups if str(g.get("id")) == group), [])
    return [member["ieee_address"] for member in members if member.get("ieee_address")]


async def has_feature(hass: HomeAssistant, ieees: list[str], name: str) -> bool:
    """Whether every one of these devices' Z2M definitions exposes a feature by this name, from bridge/devices: Z2M
    gives a group only the features its members share."""
    payload: asyncio.Future[str] = hass.loop.create_future()
    unsubscribe = await mqtt.async_subscribe(hass, bridge_topic("devices"), first_payload(payload))
    try:
        devices = json.loads(await wait(payload, _RETAINED_TIMEOUT_S, "no bridge/devices from Zigbee2MQTT"))
    finally:
        unsubscribe()
    exposing = {
        device.get("ieee_address")
        for device in devices
        if _exposes(name, (device.get("definition") or {}).get("exposes", []))
    }
    return bool(ieees) and set(ieees) <= exposing


def _exposes(name: str, features: list[dict]) -> bool:
    """Whether the feature is in this exposes list, or nested in one of its composites (a light's features)."""
    return any(feature.get("name") == name or _exposes(name, feature.get("features", [])) for feature in features)


async def ensure_options(
    hass: HomeAssistant,
    kind: Literal["device", "group"],
    z2m_ids: list[str],
    wanted: Callable[[dict], dict],
    changed: Callable[[str], None],
) -> None:
    """Set each entity's options to what `wanted` returns from its current ones, where that is anything.

    Reads Z2M's settings on every call rather than caching them, so a user who changes an option is seen. Calls
    `changed` with each ID as Z2M confirms its options, so one set before a later failure is still reported; raises
    when bridge/info or a reply doesn't come, or a reply is an error.
    """
    section = f"{kind}s"
    pending: dict[str, asyncio.Future[dict]] = {}

    @callback
    def on_reply(msg: mqtt.ReceiveMessage) -> None:
        try:
            answer = json.loads(msg.payload)
        except ValueError:
            return
        if isinstance(answer, dict) and (reply := pending.get(answer.get("transaction"))) and not reply.done():
            reply.set_result(answer)

    info: asyncio.Future[str] = hass.loop.create_future()
    # HA debounces subscribes, so async_subscribe returns before the broker has them. Queued together, the two
    # reach the broker in one batch: the retained bridge/info arriving shows the reply topic is subscribed too,
    # before a request goes out.
    unsubscribes = [
        await mqtt.async_subscribe(hass, bridge_topic(f"response/{kind}/options"), on_reply),
        await mqtt.async_subscribe(hass, bridge_topic("info"), first_payload(info)),
    ]
    try:
        settings = json.loads(await wait(info, _RETAINED_TIMEOUT_S, "no bridge/info from Zigbee2MQTT"))
        for z2m_id in z2m_ids:
            if not (options := wanted(settings.get("config", {}).get(section, {}).get(z2m_id, {}))):
                continue
            transaction = uuid4().hex
            pending[transaction] = hass.loop.create_future()
            await hass.services.async_call(
                "mqtt",
                "publish",
                {
                    "topic": bridge_topic(f"request/{kind}/options"),
                    "payload": json.dumps({"id": z2m_id, "options": options, "transaction": transaction}),
                },
                blocking=True,
            )
            answer = await wait(pending[transaction], _REPLY_TIMEOUT_S, "no reply from Zigbee2MQTT")
            if answer.get("status") != "ok":
                raise RuntimeError(answer.get("error") or f"status {answer.get('status')}")
            changed(z2m_id)
    finally:
        for unsubscribe in unsubscribes:
            unsubscribe()


def first_payload(future: asyncio.Future[str]) -> Callable[[mqtt.ReceiveMessage], None]:
    """A subscription callback that resolves future with the first message's payload."""

    @callback
    def received(msg: mqtt.ReceiveMessage) -> None:
        if not future.done():
            future.set_result(msg.payload)

    return received


async def wait(future: asyncio.Future[Any], timeout: float, what: str) -> Any:
    """The future's result, or TimeoutError(what) when it takes longer than timeout."""
    try:
        async with asyncio.timeout(timeout):
            return await future
    except TimeoutError:
        raise TimeoutError(what) from None
