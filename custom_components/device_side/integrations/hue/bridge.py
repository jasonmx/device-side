"""The core hue integration's bridge, through aiohue's v2 API: the bridge behind a target, group members, writes."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .transition_cache import BRIGHTNESS, COLOR_TEMP
from ...core.models import Target
from ...core.resolver import resolve
from ...core.runtime import get_runtime

if TYPE_CHECKING:
    from aiohue.v2 import HueBridgeV2
    from aiohue.v2.controllers.groups import GroupedLightController
    from aiohue.v2.controllers.lights import LightsController

# The delta object whose stop halts each attribute's fade.
DELTAS = {BRIGHTNESS: "dimming_delta", COLOR_TEMP: "color_temperature_delta"}


def bridge_api(target: Target) -> HueBridgeV2 | None:
    """The v2 API of the bridge behind the target, or None on a v1 bridge.

    The core hue integration keeps its HueBridge on the config entry; HueBridge.api is a HueBridgeV2 from API 2 on.
    """
    bridge = getattr(target.config_entry, "runtime_data", None)
    if bridge is None or getattr(bridge, "api_version", 1) < 2:
        return None
    return bridge.api


def resource_id(target: Target) -> str:
    """The bridge's id for the light, grouped_light or scene: core's hue integration uses it as the unique_id."""
    return target.entry.unique_id


def controller(api: HueBridgeV2, target: Target) -> LightsController | GroupedLightController:
    """The controller that reads and writes the target as one resource: the room's grouped_light, or the light."""
    return api.groups.grouped_light if target.is_group else api.lights


def is_hue_group(hass: HomeAssistant, target: Target) -> bool:
    """A room or zone, which core's hue integration exposes as one light on the room's grouped_light.

    A v1 bridge's group is left as a plain target, so supports() refuses it as bridge_v1 rather than expanding it.
    """
    return bool(target.state and target.state.attributes.get("is_hue_group")) and bridge_api(target) is not None


def expand_group(hass: HomeAssistant, target: Target) -> list[Target]:
    """The room's or zone's lights that have a light entity in HA, sorted by entity_id (aiohue's order is a set's).

    Only called for a target is_hue_group accepted, which has a v2 bridge.
    """
    api = bridge_api(target)
    entities = er.async_get(hass)
    registry = get_runtime(hass).registry
    members = []
    for light in api.groups.grouped_light.get_lights(resource_id(target)):
        entity_id = entities.async_get_entity_id("light", "hue", light.id)
        if entity_id is not None and not isinstance(
            member := resolve(hass, registry, entity_id, target.entity_id), str
        ):
            members.append(member)
    return sorted(members, key=lambda member: member.entity_id)


async def write_light(
    api: HueBridgeV2,
    light_id: str,
    *,
    on: bool | None = None,
    brightness: float | None = None,
    color_temp_mirek: int | None = None,
    color_xy: tuple[float, float] | None = None,
) -> None:
    """One PUT to one light; the bridge stores what it is sent whether the light is on or off. Raises on failure."""
    await api.lights.set_state(light_id, on=on, brightness=brightness, color_temp=color_temp_mirek, color_xy=color_xy)


def stops(attributes: Iterable[str]) -> dict:
    """The PUT body fields that halt these attributes' fades where they are."""
    return {DELTAS[attribute]: {"action": "stop"} for attribute in attributes}


async def put(api: HueBridgeV2, writer: LightsController | GroupedLightController, rid: str, body: dict) -> None:
    """One raw CLIP v2 PUT to the light or grouped_light, for what aiohue has no model of (a color temperature stop).
    Raises on failure."""
    await api.request("put", f"clip/v2/resource/{writer.item_type.value}/{rid}", json=body)
