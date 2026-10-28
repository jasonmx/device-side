"""Bring HA's color back in line after a hue or saturation command that Z2M reports in a mode HA drops.

Z2M announces a color light to HA with xy or hs, never both, and after a hue or saturation command publishes the color
as hs, which HA drops for a light announced with xy (Koenkk/zigbee2mqtt#28757). So such a light's color is read live,
and while the bulb is in hs mode its own x/y is written back with no transition: the bulb doesn't change, and Z2M then
publishes xy, which HA takes. Converting Z2M's hue and saturation instead misses the bulb's own xy by up to 0.05.

A raw command (the saturation stop) and the end of a move publish nothing, and after a stop of a fade the bulb ran in
xy, Z2M's read-back carries its cached x/y, the fade's end point. So a light not in hs mode gets a color get instead,
and so does a light announced with hs after one of those, or reached through a group, whose stop Z2M reads back from
its first member only.
"""

import logging
from collections.abc import Awaitable

from homeassistant.components.light import ColorMode
from homeassistant.core import HomeAssistant

from .addressing import topic
from .bridge import publish
from .members import member_lights
from .read import Reader, reader
from ...core.models import Target

_LOGGER = logging.getLogger(__name__)

# After Z2M's own read-back of a stop, so its hs publish comes first and the write-back's xy last.
DELAY_S = 1.0
_HS_MODE = 0  # ZCL ColorMode: CurrentHueAndCurrentSaturation
_XY_SCALE = 65535  # ZCL CurrentX and CurrentY are x and y × 65535


async def write_back_xy(hass: HomeAssistant, target: Target, silent: bool = False) -> None:
    """Bring HA's color for the light, or each of the group's members, in line with the bulb's.

    silent is for a command Z2M publishes nothing after, and for a fade's end, where a live read mid-fade may have
    left HA's color behind. Never raises: a failed read or write is logged, and HA's color
    stays stale.
    """
    try:
        lights = await member_lights(hass, target) if target.is_group else [target]
        xy_only = [light for light in lights if not _announced_with_hs(light)]
        for light in lights:
            if light not in xy_only and (silent or target.is_group):
                await _logged(light, _get_color(hass, light))
        if xy_only:
            async with reader(hass, xy_only) as reading:
                for light in xy_only:
                    await _logged(light, _write_back(hass, reading, light))
    except Exception as err:  # noqa: BLE001 - the command went out; only HA's color is at stake
        _stale(target, err)


async def _logged(light: Target, step: Awaitable[None]) -> None:
    """One light's read or write, a failure logged so the group's other members still get theirs."""
    try:
        await step
    except Exception as err:  # noqa: BLE001 - as in write_back_xy
        _stale(light, err)


def _stale(target: Target, err: Exception) -> None:
    _LOGGER.warning(
        "Couldn't bring Home Assistant's color for %s in line, so it may be stale: %s", target.entity_id, err
    )


def _announced_with_hs(light: Target) -> bool:
    modes = (light.state and light.state.attributes.get("supported_color_modes")) or ()
    return ColorMode.HS in modes


async def _write_back(hass: HomeAssistant, reading: Reader, light: Target) -> None:
    color = await reading.read_cluster(light, "lightingColorCtrl", ["colorMode", "currentX", "currentY"])
    if color["colorMode"] != _HS_MODE:
        await _get_color(hass, light)
        return
    xy = {"x": round(color["currentX"] / _XY_SCALE, 4), "y": round(color["currentY"] / _XY_SCALE, 4)}
    await publish(hass, topic(light, "set"), {"color": xy, "transition": 0})


async def _get_color(hass: HomeAssistant, light: Target) -> None:
    await publish(hass, topic(light, "get"), {"color": ""})
