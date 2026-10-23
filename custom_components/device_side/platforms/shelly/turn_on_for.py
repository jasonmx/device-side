from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import address, unsupported_reason
from .rpc import TIMER_LIMITS, light_params, set_with_timer
from ...core.capabilities import CellCapabilities
from ...core.cell import Cell
from ...core.models import EntityResult, Target
from ...features.turn_on_for import TurnOnForRequest


class ShellyTurnOnFor(Cell[TurnOnForRequest]):
    """One <Component>.Set carrying on, the light fields and toggle_after."""

    feature: ClassVar[str] = "turn_on_for"
    platform: ClassVar[str] = "shelly"
    capabilities: ClassVar[CellCapabilities] = CellCapabilities(
        experimental=True,
        domains=frozenset({"light", "switch"}),
        duration=TIMER_LIMITS,
        # Light fields stay unclaimed until a tester with a Shelly dimmer or RGB light reports.
        supports_fields=frozenset(),
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target, request.fields_present())

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            params = {"on": True, "toggle_after": request.duration_s}
            if target.domain == "light":
                params |= light_params(request.light, address(target).component, target.state)
            return await set_with_timer(self, target, params)

        return await self.gather(hass, targets, send)
