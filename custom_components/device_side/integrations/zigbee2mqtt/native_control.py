"""Turn on Z2M's hue_native_control so a Hue light timed with a color lights in that color from off.

Without it, Z2M sends on and color as separate Zigbee commands, and a Hue bulb drops a color sent while
off, so it lights at its last color first. With it, Z2M sends both as one Philips-cluster command
(zigbee-herdsman-converters src/lib/philips.ts). A command to a group reads the group's options, never its
members' (zigbee2mqtt lib/extension/publish.ts), so a group with a Hue member gets the option itself.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .addressing import bridge_topic, group_id, z2m_address
from ...core.models import Target

_LOGGER = logging.getLogger(__name__)

OPTION = "hue_native_control"
# The fields Z2M sends as a separate command after on; brightness rides moveToLevelWithOnOff with it.
COLOR_FIELDS = frozenset({"color_temp_kelvin", "hs_color", "rgb_color", "xy_color"})
_HUE_MANUFACTURER = "Philips"  # Z2M's vendor string for Hue, which HA's device registry shows
# Retained topics arrive once HA's debounced subscribe reaches the broker; the reply takes one settings write.
_RETAINED_TIMEOUT_S = 2.0
_REPLY_TIMEOUT_S = 5.0


async def ensure_native_control(hass: HomeAssistant, target: Target) -> None:
    """Turn the option on for a Hue device, or a group with a Hue member, that has it off.

    Reads Z2M's settings on every call rather than caching them, so a user who turns the option off is seen.
    Never raises: on any failure it logs a warning and the call goes ahead, lighting at the last color first.
    """
    try:
        await _ensure(hass, target)
    except Exception as err:  # noqa: BLE001 - the timer still goes out; only the first moment's color is at stake
        _LOGGER.warning(
            "Couldn't turn on Zigbee2MQTT's %s for %s, so it may light at its last color first: %s",
            OPTION, target.entity_id, err,
        )


async def _ensure(hass: HomeAssistant, target: Target) -> None:
    if (group := group_id(target)) is not None:
        if not await _has_hue_member(hass, group):
            return
        kind, z2m_id, section = "group", group, "groups"
    elif target.device is not None and target.device.manufacturer == _HUE_MANUFACTURER:
        kind, z2m_id, section = "device", z2m_address(target.device), "devices"
    else:
        return

    transaction = uuid4().hex
    info: asyncio.Future[str] = hass.loop.create_future()
    reply: asyncio.Future[dict] = hass.loop.create_future()

    @callback
    def on_reply(msg: mqtt.ReceiveMessage) -> None:
        try:
            answer = json.loads(msg.payload)
        except ValueError:
            return
        if isinstance(answer, dict) and answer.get("transaction") == transaction and not reply.done():
            reply.set_result(answer)

    # HA debounces subscribes, so async_subscribe returns before the broker has them. Queued together, the two
    # reach the broker in one batch: the retained bridge/info arriving shows the reply topic is subscribed too,
    # before the request goes out.
    unsubscribes = [
        await mqtt.async_subscribe(hass, bridge_topic(f"response/{kind}/options"), on_reply),
        await mqtt.async_subscribe(hass, bridge_topic("info"), _first_payload(info)),
    ]
    try:
        settings = json.loads(await _wait(info, _RETAINED_TIMEOUT_S, "no bridge/info from Zigbee2MQTT"))
        if settings.get("config", {}).get(section, {}).get(z2m_id, {}).get(OPTION) is True:
            return
        await hass.services.async_call(
            "mqtt",
            "publish",
            {
                "topic": bridge_topic(f"request/{kind}/options"),
                "payload": json.dumps({"id": z2m_id, "options": {OPTION: True}, "transaction": transaction}),
            },
            blocking=True,
        )
        answer = await _wait(reply, _REPLY_TIMEOUT_S, "no reply from Zigbee2MQTT")
    finally:
        for unsubscribe in unsubscribes:
            unsubscribe()

    if answer.get("status") != "ok":
        raise RuntimeError(answer.get("error") or f"status {answer.get('status')}")
    _LOGGER.info(
        "Turned on Zigbee2MQTT's %s for %s, so a timer with a color lights in that color from off",
        OPTION, target.entity_id,
    )


async def _has_hue_member(hass: HomeAssistant, group: str) -> bool:
    payload: asyncio.Future[str] = hass.loop.create_future()
    unsubscribe = await mqtt.async_subscribe(hass, bridge_topic("groups"), _first_payload(payload))
    try:
        groups = json.loads(await _wait(payload, _RETAINED_TIMEOUT_S, "no bridge/groups from Zigbee2MQTT"))
    finally:
        unsubscribe()
    members = next((g.get("members", []) for g in groups if str(g.get("id")) == group), [])
    registry = dr.async_get(hass)
    for member in members:
        device = registry.async_get_device(identifiers={("mqtt", f"zigbee2mqtt_{member.get('ieee_address')}")})
        if device is not None and device.manufacturer == _HUE_MANUFACTURER:
            return True
    return False


def _first_payload(future: asyncio.Future[str]) -> Callable[[mqtt.ReceiveMessage], None]:
    """A subscription callback that resolves future with the first message's payload."""

    @callback
    def received(msg: mqtt.ReceiveMessage) -> None:
        if not future.done():
            future.set_result(msg.payload)

    return received


async def _wait(future: asyncio.Future[Any], timeout: float, what: str) -> Any:
    """The future's result, or TimeoutError(what) when it takes longer than timeout."""
    try:
        async with asyncio.timeout(timeout):
            return await future
    except TimeoutError:
        raise TimeoutError(what) from None
