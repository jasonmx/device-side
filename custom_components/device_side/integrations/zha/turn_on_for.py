"""ZHA turn_on_for: optional light.turn_on for fields, OnWithTimedOff through zha.issue_zigbee_cluster_command (or
one zha.issue_zigbee_group_command for a ZHA group's members), then an OnOff and OnTime read-back per light."""

import asyncio
import logging
from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import entity_registry as er

from . import zcl
from .addressing import Address, address, group_id, unsupported_reason
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

    The dispatcher expands a ZHA group entity into its member lights (groups.expand_group). Members that came from
    the same group get one groupcast, so they start in lockstep: one light.turn_on on the group entity for fields,
    then one OnWithTimedOff to the group. Expanding them into one command each would start them a slot apart under
    max_concurrency, visibly so in a large group (docs/plans/2026-10-27-zha-groups-probe.md). Every other target
    gets its own command.

    issue_zigbee_cluster_command and issue_zigbee_group_command are admin-only actions, so the call carries the
    caller's context: a non-admin caller is refused by ZHA, not let through with Device Side's own rights. The zha
    library raises on a unicast delivery failure or a non-success ZCL status, so a unicast that returns was
    accepted; a groupcast returns at once with no delivery feedback, and a member that can't run the timer drops
    it silently. So each light is read back either way: a new timer replaces a running one, so reading OnTime
    straight back shows whether ours is running: CONFIRMED when it sits within _READBACK_SLACK_TENTHS under the
    request and OnOff reads on, otherwise SENT with a detail. OnTime alone is not proof: a Tuya TS011F plug stores
    it as its own countdown and stays off.
    """

    action: ClassVar[str] = "turn_on_for"
    integration: ClassVar[str] = "zha"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        # Zigbee plugs and switches rarely honor OnWithTimedOff (the rig's Tuya TS011F stores OnTime as a countdown
        # and never switches on), so switch stays out of scope until users ask.
        domains=frozenset({"light"}),
        duration=_TIMER_LIMITS,
        fields=frozenset({"brightness", "color_temp_kelvin"}),
        max_concurrency=2,
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target)

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        on_time = round(request.duration_s * 10)
        groups: dict[tuple[str, int], list[Target]] = {}
        singles: list[Target] = []
        for target in targets:
            if (gid := _via_zha_group(hass, target)) is not None:
                groups.setdefault((target.via_group, gid), []).append(target)
            else:
                singles.append(target)

        async def send(target: Target) -> EntityResult:
            return await self._unicast(hass, request, target, on_time)

        runs = [self._groupcast(hass, request, *group, members, on_time) for group, members in groups.items()]
        batches = await asyncio.gather(self.gather(hass, singles, send), *runs)
        return [result for batch in batches for result in batch]

    async def _unicast(
        self, hass: HomeAssistant, request: TurnOnForRequest, target: Target, on_time: int
    ) -> EntityResult:
        addr = address(target.entry.unique_id)  # supports() refused the targets it can't address
        if request.light.present():
            await self._turn_on(hass, request, target.entity_id)
        try:
            await zcl.command(
                hass,
                addr,
                zcl.ON_OFF_CLUSTER,
                _ON_WITH_TIMED_OFF,
                {"on_off_control": 0, "on_time": on_time, "off_wait_time": 0},
                request.context,
            )
        except Unauthorized:
            return self.result(target, Status.REJECTED, detail="admin_required")
        return await self._read_back(hass, target, addr, on_time)

    async def _groupcast(
        self,
        hass: HomeAssistant,
        request: TurnOnForRequest,
        group_entity: str,
        gid: int,
        members: list[Target],
        on_time: int,
    ) -> list[EntityResult]:
        # Under the same limits as a unicast, held for the commands only: the read-backs take them again.
        integration_limit, adapter_limit = self.limits(hass)
        try:
            async with integration_limit, adapter_limit:
                if request.light.present():
                    await self._turn_on(hass, request, group_entity)
                await hass.services.async_call(
                    "zha",
                    "issue_zigbee_group_command",
                    {
                        "group": gid,
                        "cluster_id": zcl.ON_OFF_CLUSTER,
                        "command": _ON_WITH_TIMED_OFF,
                        # Positional only: on/off control, on time, off wait time.
                        "args": [0, on_time, 0],
                    },
                    blocking=True,
                    context=request.context,
                )
        except Unauthorized:
            return [self.result(target, Status.REJECTED, detail="admin_required") for target in members]
        except Exception as err:  # noqa: BLE001 - as in gather(): one group's failure must not abort the room
            _LOGGER.warning("%s on %s failed for %s: %s", self.action, self.integration, group_entity, err)
            return [self.result(target, Status.REJECTED, detail="error") for target in members]

        async def read_back(target: Target) -> EntityResult:
            # supports() refused any member without an address, so address() can't be None here.
            return await self._read_back(hass, target, address(target.entry.unique_id), on_time)

        return await self.gather(hass, members, read_back)

    async def _turn_on(self, hass: HomeAssistant, request: TurnOnForRequest, entity_id: str) -> None:
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": entity_id, **request.light.as_turn_on_data()},
            blocking=True,
            context=request.context,
        )

    async def _read_back(self, hass: HomeAssistant, target: Target, addr: Address, on_time: int) -> EntityResult:
        # The comparison sits in the try too: a value it can't compare is a failed read, not a failed command.
        # OnTime is optional: a light without it (the rig's Sengled E11-G13) can't run the timer, which a groupcast
        # doesn't report, so it reads as no timer: not_on, or timer_not_reported once fields have turned it on. The
        # Sengled, a Zigbee end device, takes the group's light.turn_on late, so it reads not_on, then comes on.
        try:
            read = await zcl.read_attributes(hass, addr, zcl.ON_OFF_CLUSTER, (zcl.ON_OFF,), optional=(zcl.ON_TIME,))
            on_off, remaining = read[zcl.ON_OFF], read.get(zcl.ON_TIME, 0)
            if on_off not in (0, 1):  # zigpy's Bool and Python's bool both equal 0 or 1; anything else is no answer
                raise ValueError(f"OnOff read {on_off!r}")
            running = 0 < remaining and on_time - _READBACK_SLACK_TENTHS <= remaining <= on_time
        except Exception as err:  # noqa: BLE001 - zha and zigpy errors can't be imported here; see zcl.py
            _LOGGER.debug("%s read-back failed for %s: %s", self.action, target.entity_id, err)
            return self.result(target, Status.SENT, detail="readback_failed")
        if not on_off:
            return self.result(target, Status.SENT, detail="not_on")
        if running:
            return self.result(target, Status.CONFIRMED)
        return self.result(target, Status.SENT, detail="timer_not_reported")


def _via_zha_group(hass: HomeAssistant, target: Target) -> int | None:
    """The Zigbee group ID of the ZHA group the target was expanded from, or None."""
    if target.via_group is None or (entry := er.async_get(hass).async_get(target.via_group)) is None:
        return None
    return group_id(entry.unique_id) if entry.platform == "zha" else None
