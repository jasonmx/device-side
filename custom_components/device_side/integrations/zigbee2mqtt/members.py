"""A Z2M group's member lights, as targets: only Z2M's bridge/groups knows who they are."""

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .addressing import group_id, state_topic
from .bridge import group_members
from ...core.models import Target
from ...core.resolver import resolve_members
from ...core.runtime import get_runtime


async def member_lights(hass: HomeAssistant, group: Target) -> list[Target]:
    """The group's member lights that HA has and that are available, one per device.

    An unavailable member is left out, as the dispatcher leaves one out when it expands a group, and so is one HA
    has no light for.
    """
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    unique_ids = []
    for address in await group_members(hass, group_id(group)):
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
