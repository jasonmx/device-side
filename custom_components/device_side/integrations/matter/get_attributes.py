"""Matter get_attributes: the on/off timer, from a live read of OnOff.OnTime."""

from datetime import datetime
from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .addressing import (
    endpoint_id_from_unique_id,
    matter_client,
    node_id_from_unique_id,
    ontime_attr_path,
    unsupported_reason,
)
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope
from ...core.timer import timer_row


def on_time_row(on_time: object, now: datetime) -> dict:
    """One target's row from its OnTime, in tenths of a second.

    OnTime > 0 alone means a timer runs: the spec counts it down only while the plug is on, and Off zeroes it.
    Matter has no turn_off_for here, so the timer always turns the target off.
    """
    if isinstance(on_time, int) and on_time > 0:
        return {"timer": timer_row("off", on_time / 10, now)}
    return {}


class MatterGetAttributes(Adapter[Request]):
    """One live OnTime read per target; a device error raises."""

    action: ClassVar[str] = "get_attributes"
    integration: ClassVar[str] = "matter"
    scope: ClassVar[AdapterScope] = AdapterScope(
        # Plugs only: Matter lights carry the same attribute but wait for a tester's report.
        domains=frozenset({"switch"}),
        fields=frozenset(),
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(hass, target)

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        async def read(target: Target) -> EntityResult:
            # Live, not the node cache: the plug never reports OnTime on its subscription, so the cache reads 0
            # while a timer runs (probed, docs/plans/2026-10-28-matter-get-attributes.md).
            path = ontime_attr_path(endpoint_id_from_unique_id(target.entry.unique_id))
            client = matter_client(hass, target.entry.config_entry_id)  # supports() refused the targets without one
            answer = await client.read_attribute(
                node_id=node_id_from_unique_id(target.entry.unique_id), attribute_path=path
            )
            return self.result(target, Status.CONFIRMED, data=on_time_row(answer.get(path), dt_util.utcnow()))

        return await self.gather(hass, targets, read)
