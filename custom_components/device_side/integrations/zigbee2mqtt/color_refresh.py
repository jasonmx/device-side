"""Have Z2M read and publish a light's color where its own read-back after a color command doesn't.

A raw command (the saturation stop) and the end of a move publish nothing, and after a stop of a fade the bulb ran in
xy, Z2M's read-back carries its cached x/y, the fade's end point. Z2M reads a group's stop back from its first member
only. So after those, each light gets a color get, and Z2M publishes the color it reads.

HA takes the color in whichever mode Z2M publishes it only while the light is announced with both (color_modes, on by
default). With that off, HA drops an hs color after a hue or saturation stop and keeps showing the old one
(Koenkk/zigbee2mqtt#28757).
"""

import logging

from homeassistant.core import HomeAssistant

from .addressing import topic
from .bridge import publish
from .members import member_lights
from ...core.models import Target

_LOGGER = logging.getLogger(__name__)

# After Z2M's own read-back of a stop, so its publish comes first and the one the get brings last.
DELAY_S = 1.0


async def refresh_color(hass: HomeAssistant, target: Target, silent: bool = False) -> None:
    """Get the color of the light, or each of the group's members, after a color command Z2M won't read back right.

    silent is for a command Z2M publishes nothing after, and for a fade's end, where a live read mid-fade may have
    left HA's color behind. Never raises: a failed get is logged, and HA's color stays stale.
    """
    if not (silent or target.is_group):
        return
    try:
        lights = await member_lights(hass, target) if target.is_group else [target]
    except Exception as err:  # noqa: BLE001 - the command went out; only HA's color is at stake
        _stale(target, err)
        return
    for light in lights:
        try:
            await publish(hass, topic(light, "get"), {"color": ""})
        except Exception as err:  # noqa: BLE001 - as above, and the group's other members still get theirs
            _stale(light, err)


def _stale(target: Target, err: Exception) -> None:
    _LOGGER.warning("Couldn't refresh Home Assistant's color for %s, so it may be stale: %s", target.entity_id, err)
