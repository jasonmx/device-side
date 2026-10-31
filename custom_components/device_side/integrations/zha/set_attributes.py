"""ZHA set_attributes: MoveTo commands with the ExecuteIfOff override through zha.issue_zigbee_cluster_command, so a
light that is off stores the values and stays off; then an update_entity so HA shows them."""

import logging
from typing import Any, ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from . import zcl
from .addressing import address, unsupported_reason
from ...actions.set_attributes import SetAttributesRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope
from ...core.zcl_write import (
    Command,
    MoveToColor,
    MoveToColorTemp,
    MoveToHueAndSaturation,
    MoveToLevel,
    commands,
    wants_level,
)

# 0.4 s, the Hue bridge's default write fade, so a call looks alike on both; a light that is off doesn't fade.
# The override sets ExecuteIfOff for this command only, so the light takes it while off; Options stays untouched.
_EXECUTE_IF_OFF = {"transition_time": 4, "options_mask": 1, "options_override": 1}

# Models that don't store a MoveToLevel while off: the Sengled E11-G13 jumps CurrentLevel to 255 with or without the
# override and comes on at full (docs/integrations.md, ZHA tested behavior).
_DROPS_WHILE_OFF = frozenset({"E11-G13"})

Wire = tuple[int, int, dict[str, Any]]


def _wire(command: Command) -> Wire:
    """The command as zha's (cluster, command, params), with the fade and the override."""
    match command:
        case MoveToLevel(level):
            return zcl.LEVEL_CLUSTER, zcl.MOVE_TO_LEVEL, {"level": level, **_EXECUTE_IF_OFF}
        case MoveToColorTemp(mireds):
            return zcl.COLOR_CLUSTER, zcl.MOVE_TO_COLOR_TEMP, {"color_temp_mireds": mireds, **_EXECUTE_IF_OFF}
        case MoveToColor(x, y):
            params = {"color_x": round(x * 65535), "color_y": round(y * 65535)}
            return zcl.COLOR_CLUSTER, zcl.MOVE_TO_COLOR, {**params, **_EXECUTE_IF_OFF}
        case MoveToHueAndSaturation(hue, saturation):
            params = {"hue": hue, "saturation": saturation}
            return zcl.COLOR_CLUSTER, zcl.MOVE_TO_HUE_AND_SATURATION, {**params, **_EXECUTE_IF_OFF}


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
                for cluster_id, command_id, params in map(_wire, sent):
                    await zcl.command(hass, addr, cluster_id, command_id, params, request.context)
            except Unauthorized:
                return self.result(target, Status.REJECTED, detail="admin_required")
            finally:  # a later command failing still leaves the earlier ones landed
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
