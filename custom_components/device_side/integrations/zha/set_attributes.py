"""ZHA set_attributes: MoveTo commands with the ExecuteIfOff override through zha.issue_zigbee_cluster_command, so a
light that is off stores the values and stays off; then an update_entity so HA shows them."""

import logging
from typing import Any, ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.util.color import (
    color_hs_to_xy,
    color_temperature_kelvin_to_mired,
    color_temperature_to_hs,
    color_xy_to_hs,
)

from . import zcl
from .addressing import address, unsupported_reason
from ...actions.set_attributes import SetAttributesRequest
from ...core.adapter import Adapter
from ...core.color import color_xy
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope

# 0.4 s, the Hue bridge's default write fade, so a call looks alike on both; a light that is off doesn't fade.
# The override sets ExecuteIfOff for this command only, so the light takes it while off; Options stays untouched.
_EXECUTE_IF_OFF = {"transition_time": 4, "options_mask": 1, "options_override": 1}

# Models that don't store a MoveToLevel while off: the Sengled E11-G13 jumps CurrentLevel to 255 with or without the
# override and comes on at full (docs/integrations.md, ZHA tested behavior).
_DROPS_WHILE_OFF = frozenset({"E11-G13"})

_COLOR_MODES = frozenset({"xy", "hs"})

Command = tuple[int, int, dict[str, Any]]


def _level(percent: float) -> int:
    """CurrentLevel for a brightness percent; 0 is the lowest level, 1, as Hue sets its lowest."""
    return max(1, round(percent * 254 / 100))


def _brightness(request: SetAttributesRequest, current_level: int | None) -> Command | None:
    """The MoveToLevel for the request: its brightness, or the current level clamped to min/max; None if unchanged."""
    if request.brightness is not None:
        level = _level(request.brightness)
    else:
        percent = current_level * 100 / 254
        if request.min_brightness is not None:
            percent = max(request.min_brightness, percent)
        if request.max_brightness is not None:
            percent = min(request.max_brightness, percent)
        if (level := _level(percent)) == current_level:
            return None
    return zcl.LEVEL_CLUSTER, zcl.MOVE_TO_LEVEL, {"level": level, **_EXECUTE_IF_OFF}


def _mireds(kelvin: int, attrs: dict) -> int:
    """The kelvin as mireds, within the light's own range where its state gives one."""
    mireds = color_temperature_kelvin_to_mired(kelvin)
    if (warmest := attrs.get("min_color_temp_kelvin")) is not None:
        mireds = min(mireds, color_temperature_kelvin_to_mired(warmest))
    if (coolest := attrs.get("max_color_temp_kelvin")) is not None:
        mireds = max(mireds, color_temperature_kelvin_to_mired(coolest))
    return mireds


def _color(xy: tuple[float, float], modes: set[str]) -> Command:
    """MoveToColor on an xy light, else MoveToHueAndSaturation. The light clamps the color to its own gamut."""
    if "xy" in modes:
        params = {"color_x": round(xy[0] * 65535), "color_y": round(xy[1] * 65535)}
        return zcl.COLOR_CLUSTER, zcl.MOVE_TO_COLOR, {**params, **_EXECUTE_IF_OFF}
    hue, saturation = color_xy_to_hs(*xy)
    params = {"hue": round(hue * 254 / 360), "saturation": round(saturation * 254 / 100)}
    return zcl.COLOR_CLUSTER, zcl.MOVE_TO_HUE_AND_SATURATION, {**params, **_EXECUTE_IF_OFF}


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
            params = {"color_temp_mireds": _mireds(kelvin, attrs), **_EXECUTE_IF_OFF}
            sent.append((zcl.COLOR_CLUSTER, zcl.MOVE_TO_COLOR_TEMP, params))
        else:
            dropped = True
    return sent, dropped


_LOGGER = logging.getLogger(__name__)


class ZHASetAttributes(Adapter[SetAttributesRequest]):
    """Send each light its MoveTo commands one after another, never the WithOnOff variants, then update_entity it.

    The ExecuteIfOff override makes a light that is off store the values and stay off (probe 13a). The zha library
    raises on a delivery failure or a non-success ZCL status, so a light whose commands return is SENT; nothing reads
    back, so a bulb that ignores the override also reports SENT. ZHA never applies a color temperature report, hence
    the update_entity. The dispatcher expands a ZHA group into its members, written one at a time: a groupcast has no
    delivery feedback. A field the light can't take is dropped and the result says so, as on Hue.
    """

    action: ClassVar[str] = "set_attributes"
    integration: ClassVar[str] = "zha"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        domains=frozenset({"light"}),
        fields=frozenset(
            {"brightness", "color_temp_kelvin", "hs_color", "rgb_color", "xy_color", "min_brightness", "max_brightness"}
        ),
        max_concurrency=2,
    )

    def supports(self, hass: HomeAssistant, request: SetAttributesRequest, target: Target) -> str | None:
        if reason := super().supports(hass, request, target) or unsupported_reason(target):
            return reason
        if target.device is not None and target.device.model in _DROPS_WHILE_OFF:
            return "execute_if_off_unsupported"
        return None

    async def execute(
        self, hass: HomeAssistant, request: SetAttributesRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            addr = address(target.entry.unique_id)  # supports() refused the targets it can't address
            # supported_color_modes stays in the state while the light is off.
            attrs = dict(target.state.attributes) if target.state else {}
            modes = set(attrs.get("supported_color_modes") or ())
            current_level = None
            if wants_level(request, modes):
                read = await zcl.read_attributes(hass, addr, zcl.LEVEL_CLUSTER, (zcl.CURRENT_LEVEL,))
                current_level = read[zcl.CURRENT_LEVEL]
            sent, dropped = commands(request, modes, attrs, current_level)
            detail = "fields_dropped" if dropped else None
            if not sent:
                return self.result(target, Status.UNCHANGED, detail=detail or "within_limits")
            try:
                for cluster_id, command_id, params in sent:
                    await zcl.command(hass, addr, cluster_id, command_id, params, request.context)
            except Unauthorized:
                return self.result(target, Status.REJECTED, detail="admin_required")
            await self._refresh(hass, request, target.entity_id)
            return self.result(target, Status.SENT, detail=detail)

        return await self.gather(hass, targets, send)

    async def _refresh(self, hass: HomeAssistant, request: SetAttributesRequest, entity_id: str) -> None:
        try:
            await hass.services.async_call(
                "homeassistant", "update_entity", {"entity_id": entity_id}, blocking=True, context=request.context
            )
        except Exception as err:  # noqa: BLE001 - the write landed; a stale HA state is no reason to fail it
            _LOGGER.warning("update_entity after %s failed for %s: %s", self.action, entity_id, err)
