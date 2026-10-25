"""ZHA turn_on_for: optional light.turn_on for fields, OnWithTimedOff through zha.issue_zigbee_cluster_command,
then an OnOff and OnTime read-back."""

import logging
from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from . import zcl
from .addressing import address
from ...actions.turn_on_for import TurnOnForRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope, DurationLimits

# OnWithTimedOff.on_time is a uint16 in tenths of a second; 0xFFFF is reserved, so 65534 tenths is the most.
_TIMER_LIMITS = DurationLimits(min_s=0.1, max_s=6553.4)

_ON_WITH_TIMED_OFF = 0x42

# OnTime counts down live, so the read-back lands a little under the request; matches the rig's ZHA tolerance
# (tests/rig/inventory.py TOLERANCE_S["zha"]).
_READBACK_SLACK_TENTHS = 30

_LOGGER = logging.getLogger(__name__)


class ZHATurnOnFor(Adapter[TurnOnForRequest]):
    """Send OnWithTimedOff on the OnOff cluster; light.turn_on first when fields are present.

    issue_zigbee_cluster_command is an admin-only action, so the call carries the caller's context: a non-admin
    caller is refused by ZHA, not let through with Device Side's own rights. The zha library raises on a
    delivery failure or a non-success ZCL status, so a command that returns was accepted. A new timer replaces a
    running one, so reading OnTime straight back shows whether ours is running: CONFIRMED when it sits within
    _READBACK_SLACK_TENTHS under the request and OnOff reads on, otherwise SENT with a detail. OnTime alone is
    not proof: a Tuya TS011F plug stores it as its own countdown and stays off.
    """

    action: ClassVar[str] = "turn_on_for"
    integration: ClassVar[str] = "zha"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        # The rig's ZHA plug (Tuya TS011F) stores OnTime as a countdown and never switches on, so switch stays
        # out of scope until a plug that honors OnWithTimedOff is tested.
        domains=frozenset({"light"}),
        duration=_TIMER_LIMITS,
        fields=frozenset({"brightness", "color_temp_kelvin"}),
        max_concurrency=2,
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if address(target.entry.unique_id) is None:
            return "not_addressable"
        return None

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            if (addr := address(target.entry.unique_id)) is None:  # supports() already refused this target
                return self.result(target, Status.UNSUPPORTED, detail="not_addressable")

            if request.light.present():
                await hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": target.entity_id, **request.light.as_turn_on_data()},
                    blocking=True,
                    context=request.context,
                )
            on_time = round(request.duration_s * 10)
            try:
                await hass.services.async_call(
                    "zha",
                    "issue_zigbee_cluster_command",
                    {
                        "ieee": addr.ieee,
                        "endpoint_id": addr.endpoint_id,
                        "cluster_id": zcl.ON_OFF_CLUSTER,
                        "cluster_type": "in",
                        "command": _ON_WITH_TIMED_OFF,
                        "command_type": "server",
                        "params": {
                            "on_off_control": 0,
                            "on_time": on_time,
                            "off_wait_time": 0,
                        },
                    },
                    blocking=True,
                    context=request.context,
                )
            except Unauthorized:
                return self.result(target, Status.REJECTED, detail="admin_required")

            # The comparison sits in the try too: a value it can't compare is a failed read, not a failed command.
            try:
                read = await zcl.read_attributes(hass, addr, zcl.ON_OFF_CLUSTER, (zcl.ON_OFF, zcl.ON_TIME))
                is_on, remaining = bool(read[zcl.ON_OFF]), read[zcl.ON_TIME]
                running = 0 < remaining and on_time - _READBACK_SLACK_TENTHS <= remaining <= on_time
            except Exception as err:  # noqa: BLE001 - zha and zigpy errors can't be imported here; see zcl.py
                _LOGGER.debug("%s read-back failed for %s: %s", self.action, target.entity_id, err)
                return self.result(target, Status.SENT, detail="readback_failed")
            if not is_on:
                return self.result(target, Status.SENT, detail="not_on")
            if running:
                return self.result(target, Status.CONFIRMED)
            return self.result(target, Status.SENT, detail="timer_not_reported")

        return await self.gather(hass, targets, send)
