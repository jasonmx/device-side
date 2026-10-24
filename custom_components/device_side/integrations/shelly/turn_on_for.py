from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import address, unsupported_reason
from .rpc import TIMER_LIMITS, light_params, set_with_timer
from ...actions.turn_on_for import TurnOnForRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Target
from ...core.scope import AdapterScope


class ShellyTurnOnFor(Adapter[TurnOnForRequest]):
    """One <Component>.Set carrying on, the light fields and toggle_after."""

    action: ClassVar[str] = "turn_on_for"
    integration: ClassVar[str] = "shelly"
    scope: ClassVar[AdapterScope] = AdapterScope(
        domains=frozenset({"light", "switch"}),
        duration=TIMER_LIMITS,
        # Light fields stay out of scope until a tester with a Shelly Light, CCT or RGB* component reports.
        fields=frozenset(),
        # A relay shown as a light sends the same Switch.Set; Light, CCT and RGB* wait for a tester's report.
        capabilities=frozenset({"Switch"}),
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(
            target, request.fields_present(), self.scope.capabilities
        )

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            params = {"on": True, "toggle_after": request.duration_s}
            if target.domain == "light":
                params |= light_params(request.light, address(target).component, target.state)
            return await set_with_timer(self, target, params)

        return await self.gather(hass, targets, send)
