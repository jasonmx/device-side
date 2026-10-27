from dataclasses import replace
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import COMPONENT_FIELDS, address, unsupported_reason
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
        fields=frozenset({"brightness", "color_temp_kelvin", "rgb_color", "transition"}),
        # A relay shown as a light sends the same Switch.Set; Light, CCT, RGB and RGBW wait for a tester's report.
        capabilities=frozenset({"Switch", "RGBCCT"}),
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target, self.scope.capabilities)

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            # The dispatcher drops the fields HA's state says the light lacks; the component is the device's word.
            component = address(target).component
            dropped = request.light.present() - COMPONENT_FIELDS[component]
            params = {"on": True, "toggle_after": request.duration_s}
            params |= light_params(request.light.without(dropped), component, target.state)
            result = await set_with_timer(self, target, params)
            return replace(result, detail="fields_dropped") if dropped and result.detail is None else result

        return await self.gather(hass, targets, send)
