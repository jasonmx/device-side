"""Zigbee2MQTT get_attributes: on/off timer, brightness, color temperature and color, read live from each bulb."""

from datetime import datetime
from typing import ClassVar

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .addressing import group_id, state_topic, topic
from .bridge import group_members
from .read import Reader, reader
from ...core.adapter import Adapter
from ...core.dispatcher import EMPTY_GROUP
from ...core.models import EntityResult, Request, Status, Target
from ...core.resolver import resolve_members
from ...core.runtime import get_runtime
from ...core.scope import AdapterScope
from ...core.zcl_row import average, zcl_row


class Z2MGetAttributes(Adapter[Request]):
    """One row per target from live ZCL reads (read.py): Hue bulbs on Z2M don't report, so HA's state can be stale.

    A group's row follows Hue's room row: its members are read one after another and averaged over the lit ones,
    or over all of them when every member is off. It has a timer only when every lit member runs one, and then it
    is the longest. A read that fails raises, so the call raises targets_failed.
    """

    action: ClassVar[str] = "get_attributes"
    integration: ClassVar[str] = "zigbee2mqtt"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        # Switches stay out of scope, as in turn_on_for.
        domains=frozenset({"light"}),
        confirmable=True,
        native_groups=True,  # read through its members, which only Z2M's bridge/groups knows
    )

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if topic(target, "set") is None or (not target.is_group and state_topic(target) is None):
            return "not_addressable"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        async def read(target: Target) -> EntityResult:
            if not target.is_group:
                async with reader(hass, [target]) as device:
                    return self.result(target, Status.CONFIRMED, data=zcl_row(*await _read(device, target)))
            members = _members(hass, target, await group_members(hass, group_id(target)))
            if not members:
                return self.result(target, Status.UNSUPPORTED, detail=EMPTY_GROUP)
            # One after another inside the group's own task: gathering them would nest the concurrency limits.
            async with reader(hass, members) as device:
                reads = [await _read(device, member) for member in members]
            lit = [(attributes, now) for attributes, now in reads if attributes.get("onOff")]
            return self.result(
                target, Status.CONFIRMED, data=average([zcl_row(*one) for one in lit or reads])
            )

        return await self.gather(hass, targets, read)


async def _read(device: Reader, target: Target) -> tuple[dict, datetime]:
    """The target's attributes, and when they were read, which a timer's end counts from."""
    attributes = await device.read(target)
    return attributes, dt_util.utcnow()


def _members(hass: HomeAssistant, group: Target, addresses: list[str]) -> list[Target]:
    """The group's member lights that HA has and that are available, one per device.

    An unavailable member is left out, as the dispatcher leaves one out when it expands a group, and so is one HA
    has no light for.
    """
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    unique_ids = []
    for address in addresses:
        if (device := devices.async_get_device(identifiers={("mqtt", f"zigbee2mqtt_{address}")})) is None:
            continue
        lights = [e for e in er.async_entries_for_device(entities, device.id) if e.domain == group.domain]
        unique_ids += [lights[0].unique_id] if lights else []
    members = resolve_members(hass, get_runtime(hass).registry, group, "mqtt", unique_ids)
    return [
        member
        for member in members
        if member.state is not None and member.state.state != STATE_UNAVAILABLE and state_topic(member) is not None
    ]
