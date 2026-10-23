from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import unsupported_reason
from .rpc import TIMER_LIMITS, set_with_timer
from ...core.capabilities import CellCapabilities
from ...core.cell import Cell
from ...core.models import EntityResult, Target, TimedRequest


class ShellyTurnOffFor(Cell[TimedRequest]):
    """One <Component>.Set carrying on=False and toggle_after; the device turns itself back on."""

    feature: ClassVar[str] = "turn_off_for"
    platform: ClassVar[str] = "shelly"
    capabilities: ClassVar[CellCapabilities] = CellCapabilities(
        experimental=True,
        domains=frozenset({"light", "switch"}),
        duration=TIMER_LIMITS,
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TimedRequest, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target)

    async def execute(self, hass: HomeAssistant, request: TimedRequest, targets: list[Target]) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            return await set_with_timer(self, target, {"on": False, "toggle_after": request.duration_s})

        return await self.gather(hass, targets, send)
