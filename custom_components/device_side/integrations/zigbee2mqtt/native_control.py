"""Turn on Z2M's hue_native_control so a Hue light timed with a color lights in that color from off.

Without it, Z2M sends on and color as separate Zigbee commands, and a Hue bulb drops a color sent while
off, so it lights at its last color first. With it, Z2M sends both as one Philips-cluster command
(zigbee-herdsman-converters src/lib/philips.ts). A command to a group reads the group's options, never its
members' (zigbee2mqtt lib/extension/publish.ts), so a group with a Hue member gets the option itself.
"""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .addressing import group_id, z2m_address
from .bridge import ensure_options, group_members
from ...core.models import Target

_LOGGER = logging.getLogger(__name__)

OPTION = "hue_native_control"
# The fields Z2M sends as a separate command after on; brightness rides moveToLevelWithOnOff with it.
COLOR_FIELDS = frozenset({"color_temp_kelvin", "hs_color", "rgb_color", "xy_color"})
_HUE_MANUFACTURER = "Philips"  # Z2M's vendor string for Hue, which HA's device registry shows


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
        kind, z2m_id = "group", group
    elif target.device is not None and target.device.manufacturer == _HUE_MANUFACTURER:
        kind, z2m_id = "device", z2m_address(target.device)
    else:
        return

    def turned_on(_z2m_id: str) -> None:
        _LOGGER.info(
            "Turned on Zigbee2MQTT's %s for %s, so a timer with a color lights in that color from off",
            OPTION, target.entity_id,
        )

    await ensure_options(hass, kind, [z2m_id], lambda current: {} if current.get(OPTION) else {OPTION: True}, turned_on)


async def _has_hue_member(hass: HomeAssistant, group: str) -> bool:
    registry = dr.async_get(hass)
    for ieee in await group_members(hass, group):
        device = registry.async_get_device(identifiers={("mqtt", f"zigbee2mqtt_{ieee}")})
        if device is not None and device.manufacturer == _HUE_MANUFACTURER:
            return True
    return False
