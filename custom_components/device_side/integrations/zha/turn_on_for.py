"""ZHA turn_on_for: optional light.turn_on for fields, then OnWithTimedOff through zha.issue_zigbee_cluster_command."""

from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from .addressing import address
from ...actions.turn_on_for import TurnOnForRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope, DurationLimits

# OnWithTimedOff.on_time is a uint16 in tenths of a second; 0xFFFF is reserved, so 65534 tenths is the most.
_TIMER_LIMITS = DurationLimits(min_s=0.1, max_s=6553.4)

_ON_OFF_CLUSTER = 0x0006
_ON_WITH_TIMED_OFF = 0x42


class ZHATurnOnFor(Adapter[TurnOnForRequest]):
    """Send OnWithTimedOff on the OnOff cluster; light.turn_on first when fields are present.

    issue_zigbee_cluster_command is an admin-only action, so the call carries the caller's context: a non-admin
    caller is refused by ZHA, not let through with Device Side's own rights. The zha library raises on a
    delivery failure or a non-success ZCL status, so a result that comes back is SENT.
    """

    action: ClassVar[str] = "turn_on_for"
    integration: ClassVar[str] = "zha"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        # The rig has ZHA bulbs but no ZHA plug, so switch stays out of scope until someone tests one.
        domains=frozenset({"light"}),
        duration=_TIMER_LIMITS,
        fields=frozenset({"brightness"}),
        max_concurrency=2,
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
            try:
                await hass.services.async_call(
                    "zha",
                    "issue_zigbee_cluster_command",
                    {
                        "ieee": addr.ieee,
                        "endpoint_id": addr.endpoint_id,
                        "cluster_id": _ON_OFF_CLUSTER,
                        "cluster_type": "in",
                        "command": _ON_WITH_TIMED_OFF,
                        "command_type": "server",
                        "params": {
                            "on_off_control": 0,
                            "on_time": round(request.duration_s * 10),
                            "off_wait_time": 0,
                        },
                    },
                    blocking=True,
                    context=request.context,
                )
            except Unauthorized:
                return self.result(target, Status.REJECTED, detail="admin_required")
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)
