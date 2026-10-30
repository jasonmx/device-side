"""set_attributes as ZCL MoveTo commands, shared by the Zigbee integrations.

The commands are neutral: each adapter maps them to its own wire names (zigpy's or zigbee-herdsman's) and adds the
transition and the ExecuteIfOff override.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.util.color import (
    color_hs_to_xy,
    color_temperature_kelvin_to_mired,
    color_temperature_to_hs,
    color_xy_to_hs,
)

from .color import color_xy

if TYPE_CHECKING:  # core doesn't import actions at run time
    from ..actions.set_attributes import SetAttributesRequest

_COLOR_MODES = frozenset({"xy", "hs"})


@dataclass(frozen=True, slots=True)
class MoveToLevel:
    level: int


@dataclass(frozen=True, slots=True)
class MoveToColorTemp:
    mireds: int


@dataclass(frozen=True, slots=True)
class MoveToColor:
    """CIE xy, 0–1; the adapter scales it to the ZCL's 0–65535."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class MoveToHueAndSaturation:
    """ZCL units: both 0–254."""

    hue: int
    saturation: int


Command = MoveToLevel | MoveToColorTemp | MoveToColor | MoveToHueAndSaturation


def _level(percent: float) -> int:
    """CurrentLevel for a brightness percent; 0 is the lowest level, 1, as Hue sets its lowest."""
    return max(1, round(percent * 254 / 100))


def _brightness(request: SetAttributesRequest, current_level: int | None) -> MoveToLevel | None:
    """The MoveToLevel for the request: its brightness, or the current level clamped to min/max; None if unchanged."""
    if request.brightness is not None:
        return MoveToLevel(_level(request.brightness))
    percent = current_level * 100 / 254
    if request.min_brightness is not None:
        percent = max(request.min_brightness, percent)
    if request.max_brightness is not None:
        percent = min(request.max_brightness, percent)
    if (level := _level(percent)) == current_level:
        return None
    return MoveToLevel(level)


def clamp_mireds(mireds: int, attrs: dict) -> int:
    """The mireds within the light's own range, where its state gives one."""
    if (warmest := attrs.get("min_color_temp_kelvin")) is not None:
        mireds = min(mireds, color_temperature_kelvin_to_mired(warmest))
    if (coolest := attrs.get("max_color_temp_kelvin")) is not None:
        mireds = max(mireds, color_temperature_kelvin_to_mired(coolest))
    return mireds


def _color(xy: tuple[float, float], modes: set[str]) -> MoveToColor | MoveToHueAndSaturation:
    """MoveToColor on an xy light, else MoveToHueAndSaturation. The light clamps the color to its own gamut."""
    if "xy" in modes:
        return MoveToColor(*xy)
    hue, saturation = color_xy_to_hs(*xy)
    return MoveToHueAndSaturation(round(hue * 254 / 360), round(saturation * 254 / 100))


def wants_level(request: SetAttributesRequest, modes: set[str]) -> bool:
    """Whether the commands need the light's CurrentLevel: min/max_brightness alone, on a light that dims."""
    limits = request.min_brightness is not None or request.max_brightness is not None
    return request.brightness is None and limits and bool(modes - {"onoff"})


def commands(
    request: SetAttributesRequest, modes: set[str], attrs: dict, current_level: int | None
) -> tuple[list[Command], bool]:
    """The commands for one light, from its supported_color_modes and state attributes, and whether a field the light
    can't take was dropped. current_level is read only when wants_level() says so.

    The dispatcher already dropped what the modes rule out; what is left to drop here is for a state that lists no
    modes. Given a color and color_temp_kelvin, only the color is sent: both are Color cluster commands, so the last
    would win anyway. A color light without color temperature takes it as a color, as in core.
    """
    fields = request.light
    sent: list[Command] = []
    dropped = False
    if request.brightness is not None or request.min_brightness is not None or request.max_brightness is not None:
        if not modes - {"onoff"}:
            dropped = True
        elif (command := _brightness(request, current_level)) is not None:
            sent.append(command)
    kelvin = fields.color_temp_kelvin
    colors = bool(modes & _COLOR_MODES)
    if (xy := color_xy(fields)) is None and kelvin is not None and colors and "color_temp" not in modes:
        xy = color_hs_to_xy(*color_temperature_to_hs(kelvin))  # as core's light.turn_on converts it
    if xy is not None:
        if colors:
            sent.append(_color(xy, modes))
        else:
            dropped = True
    if kelvin is not None and not (xy is not None and colors):
        if "color_temp" in modes:
            sent.append(MoveToColorTemp(clamp_mireds(color_temperature_kelvin_to_mired(kelvin), attrs)))
        else:
            dropped = True
    return sent, dropped
