"""A get_attributes row from a Zigbee light's raw ZCL attributes, shared by the Zigbee integrations.

Attributes go by zigbee-herdsman's names (`currentLevel`, `colorMode`), the ZCL spec's in camel case.
"""

from datetime import datetime
from statistics import mean

from homeassistant.util.color import (
    color_hs_to_RGB,
    color_hs_to_xy,
    color_temperature_mired_to_kelvin,
    color_xy_to_hs,
    color_xy_to_RGB,
)

from .timer import timer_row

# ColorMode (0x0008): the attributes that set the light's color.
_HS, _XY, _COLOR_TEMP = 0, 1, 2
_MAX_LEVEL = 254  # CurrentLevel, CurrentHue and CurrentSaturation all top out at 0xFE
_MAX_XY = 65535


def zcl_row(attributes: dict, now: datetime) -> dict:
    """One light's row from the attributes read, under HA's names; what wasn't read is left out.

    Brightness is a percent of CurrentLevel, as Hue's row is. Only the color of the active ColorMode is reported,
    as core does. Lights keep these attributes while off, so they read then too. OnTime is the time left on an
    OnWithTimedOff timer, in tenths, and reads 0 with none.
    """
    row: dict = {}
    if (level := attributes.get("currentLevel")) is not None:
        row["brightness"] = round(level * 100 / _MAX_LEVEL, 1)
    row |= _color(attributes)
    if attributes.get("onOff") and attributes.get("onTime"):
        row["timer"] = timer_row("off", attributes["onTime"] / 10, now)
    return row


def _color(attributes: dict) -> dict:
    mode = attributes.get("colorMode")
    if mode == _COLOR_TEMP and attributes.get("colorTemperature"):
        return {"color_temp_kelvin": color_temperature_mired_to_kelvin(attributes["colorTemperature"])}
    if mode == _HS and "currentHue" in attributes and "currentSaturation" in attributes:
        hs = (
            round(attributes["currentHue"] * 360 / _MAX_LEVEL, 3),
            round(attributes["currentSaturation"] * 100 / _MAX_LEVEL, 3),
        )
        return {"hs_color": list(hs), "rgb_color": list(color_hs_to_RGB(*hs)), "xy_color": list(color_hs_to_xy(*hs))}
    # A light in hs mode keeps its xy current too, so one whose read left out hue and saturation reports that.
    if mode in (_HS, _XY) and "currentX" in attributes and "currentY" in attributes:
        return _xy_fields(attributes["currentX"] / _MAX_XY, attributes["currentY"] / _MAX_XY)
    return {}


def _xy_fields(x: float, y: float) -> dict:
    xy = (round(x, 4), round(y, 4))
    return {"xy_color": list(xy), "rgb_color": list(color_xy_to_RGB(*xy)), "hs_color": list(color_xy_to_hs(*xy))}


def average(rows: list[dict]) -> dict:
    """A group's row from its members' rows, chosen by the caller as Hue's room row is: the lit ones, or all.

    Brightness and color temperature average the rows that have them; xy averages too and the other colors follow
    from it. A timer is reported only when every row has one, and then it is the longest.
    """
    row: dict = {}
    if levels := [r["brightness"] for r in rows if "brightness" in r]:
        row["brightness"] = round(mean(levels), 1)
    if kelvins := [r["color_temp_kelvin"] for r in rows if "color_temp_kelvin" in r]:
        row["color_temp_kelvin"] = round(mean(kelvins))
    if xys := [r["xy_color"] for r in rows if "xy_color" in r]:
        row |= _xy_fields(mean(x for x, _ in xys), mean(y for _, y in xys))
    if rows and all("timer" in r for r in rows):
        row["timer"] = max((r["timer"] for r in rows), key=lambda timer: timer["remaining_s"])
    return row
