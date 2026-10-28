"""ZHA get_attributes: on/off timer, brightness, color temperature and color, read live off each light."""

from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_hs_to_xy,
    color_temperature_mired_to_kelvin,
    color_xy_to_hs,
    color_xy_to_RGB,
)

from . import zcl
from .addressing import address
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope
from ...core.timer import timer_row

_COLOR_MODES = frozenset({"color_temp", "hs", "xy"})

# ZCL ColorMode values; EnhancedColorMode adds 3 for enhanced hue.
_HS, _XY, _CT, _ENHANCED_HS = 0, 1, 2, 3

_COLOR_ATTRIBUTES = (
    zcl.CURRENT_HUE,
    zcl.CURRENT_SATURATION,
    zcl.CURRENT_X,
    zcl.CURRENT_Y,
    zcl.COLOR_TEMPERATURE,
    zcl.ENHANCED_CURRENT_HUE,
    zcl.ENHANCED_COLOR_MODE,
)


def light_row(on_off: dict[int, int], level: dict[int, int] | None, color: dict[int, int] | None) -> dict:
    """One light's row from its OnOff, Level and Color reads, each keyed by attribute ID; None where not read.

    Brightness is a percent, as Hue's and Shelly's are, so a read can be written back. Color is the active mode
    only, as core reports it. OnTime counts only while OnOff reads on: a Tuya TS011F counts it down while off.
    """
    row: dict = {}
    if level is not None:
        row["brightness"] = round(level[zcl.CURRENT_LEVEL] / 254 * 100, 1)
    if color is not None:
        row.update(_color(color))
    if on_off[zcl.ON_OFF] and (on_time := on_off.get(zcl.ON_TIME, 0)) > 0:
        row["timer"] = timer_row("off", on_time / 10)
    return row


def _color(color: dict[int, int]) -> dict:
    mode = color.get(zcl.ENHANCED_COLOR_MODE, color[zcl.COLOR_MODE])
    if mode == _CT and (mireds := color.get(zcl.COLOR_TEMPERATURE)):
        return {"color_temp_kelvin": color_temperature_mired_to_kelvin(mireds)}
    if mode == _XY and zcl.CURRENT_X in color and zcl.CURRENT_Y in color:
        xy = (round(color[zcl.CURRENT_X] / 65535, 4), round(color[zcl.CURRENT_Y] / 65535, 4))
        return {"xy_color": list(xy), "rgb_color": list(color_xy_to_RGB(*xy)), "hs_color": list(color_xy_to_hs(*xy))}
    if mode == _ENHANCED_HS and zcl.ENHANCED_CURRENT_HUE in color:
        hue = color[zcl.ENHANCED_CURRENT_HUE] * 360 / 65535
    elif mode == _HS and zcl.CURRENT_HUE in color:
        hue = color[zcl.CURRENT_HUE] * 360 / 254
    else:
        return {}
    if zcl.CURRENT_SATURATION not in color:
        return {}
    hs = (round(hue, 3), round(color[zcl.CURRENT_SATURATION] * 100 / 254, 3))
    return {"hs_color": list(hs), "rgb_color": list(color_hs_to_RGB(*hs)), "xy_color": list(color_hs_to_xy(*hs))}


class ZHAGetAttributes(Adapter[Request]):
    """Read OnOff, then Level and Color as the light's supported_color_modes call for, one request at a time.

    Always live, never zigpy's cache: ZHA doesn't apply color temperature reports, so the cache goes stale after a
    raw command or a bound remote, while a live read mid-transition returns where the light is. The dispatcher
    expands a ZHA group into its members, one row each. A failed read raises, rejecting that light.
    """

    action: ClassVar[str] = "get_attributes"
    integration: ClassVar[str] = "zha"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        # Zigbee plugs don't honor OnTime (see turn_on_for), so a switch row would always be empty.
        domains=frozenset({"light"}),
        max_concurrency=2,
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if address(target.entry.unique_id) is None:
            return "not_addressable"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        async def read(target: Target) -> EntityResult:
            addr = address(target.entry.unique_id)  # supports() refused the targets it can't address
            # supported_color_modes stays in the state while the light is off.
            modes = set(target.state.attributes.get("supported_color_modes") or ()) if target.state else set()
            on_off = await zcl.read_attributes(hass, addr, zcl.ON_OFF_CLUSTER, (zcl.ON_OFF,), optional=(zcl.ON_TIME,))
            level = color = None
            if modes - {"onoff"}:
                level = await zcl.read_attributes(hass, addr, zcl.LEVEL_CLUSTER, (zcl.CURRENT_LEVEL,))
            if modes & _COLOR_MODES:
                color = await zcl.read_attributes(
                    hass, addr, zcl.COLOR_CLUSTER, (zcl.COLOR_MODE,), optional=_COLOR_ATTRIBUTES
                )
            return self.result(target, Status.CONFIRMED, data=light_row(on_off, level, color))

        return await self.gather(hass, targets, read)
