"""Matter turn_on_for: OnWithTimedOff on the OnOff cluster, then OnTime read-back."""

import logging
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import (
    endpoint_id_from_unique_id,
    lt_feature,
    make_on_with_timed_off,
    matter_client,
    node_id_from_unique_id,
    ontime_attr_path,
)
from ...actions.turn_on_for import TurnOnForRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope, DurationLimits

_LOGGER = logging.getLogger(__name__)

# OnWithTimedOff.onTime is uint16 in units of 1/10 s; max = 65535 tenths = 6553.5 s.
# Use 6553.4 as the ceiling so the value stays well within uint16 after rounding.
_TIMER_LIMITS = DurationLimits(min_s=0.1, max_s=6553.4)


class MatterTurnOnFor(Adapter[TurnOnForRequest]):
    """Send OnWithTimedOff on the OnOff cluster."""

    action: ClassVar[str] = "turn_on_for"
    integration: ClassVar[str] = "matter"
    scope: ClassVar[AdapterScope] = AdapterScope(
        # Plugs only: Matter lights take the same command but wait for a tester's report.
        domains=frozenset({"switch"}),
        duration=_TIMER_LIMITS,
        fields=frozenset(),
        # capabilities=None covers every plug endpoint that passes the LT feature check.
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        reason = super().supports(hass, request, target)
        if reason:
            return reason

        node_id = node_id_from_unique_id(target.entry.unique_id)
        ep_id = endpoint_id_from_unique_id(target.entry.unique_id)
        if node_id is None or ep_id is None:
            return "not_addressable"

        client = matter_client(hass, target.entry.config_entry_id)
        if client is None:
            return "not_addressable"

        try:
            node = client.get_node(node_id)
        except Exception:  # noqa: BLE001 - node lookup can raise if the node no longer exists
            return "not_addressable"

        if node is None:
            return "not_addressable"

        if not lt_feature(node, ep_id):
            return "no_lt_feature"

        return None

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            node_id = node_id_from_unique_id(target.entry.unique_id)
            ep_id = endpoint_id_from_unique_id(target.entry.unique_id)
            client = matter_client(hass, target.entry.config_entry_id)  # supports() refused the targets without one

            on_time = round(request.duration_s * 10)
            command = make_on_with_timed_off(on_off_control=0, on_time=on_time, off_wait_time=0)
            await client.send_device_command(
                node_id=node_id,
                endpoint_id=ep_id,
                command=command,
            )

            # Optional read-back: confirm the timer is running. The client returns {path: value}.
            path = ontime_attr_path(ep_id)
            try:
                read = await client.read_attribute(node_id=node_id, attribute_path=path)
                on_time_value = read.get(path)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "turn_on_for matter read-back failed for %s: %s", target.entity_id, err
                )
                return self.result(target, Status.SENT, detail="readback_failed")

            if on_time_value:
                return self.result(target, Status.CONFIRMED)
            return self.result(target, Status.SENT, detail="timer_not_reported")

        return await self.gather(hass, targets, send)
