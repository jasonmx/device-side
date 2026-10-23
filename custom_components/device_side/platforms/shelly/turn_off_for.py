from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import unsupported_reason
from .rpc import TIMER_LIMITS, set_with_timer
from ...core.adapter import Adapter
from ...core.capabilities import AdapterCapabilities
from ...core.models import EntityResult, Target, TimedRequest


class ShellyTurnOffFor(Adapter[TimedRequest]):
    """One <Component>.Set carrying on=False and toggle_after; the device turns itself back on."""

    feature: ClassVar[str] = "turn_off_for"
    platform: ClassVar[str] = "shelly"
    capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        experimental=True,
        domains=frozenset({"light", "switch"}),
        duration=TIMER_LIMITS,
        confirmable=True,
        # A relay shown as a light sends the same Switch.Set; Light, CCT and RGB* wait for a tester's report.
        components=frozenset({"Switch"}),
    )

    def supports(self, hass: HomeAssistant, request: TimedRequest, target: Target) -> str | None:
        components = self.capabilities.components
        return super().supports(hass, request, target) or unsupported_reason(target, components=components)

    async def execute(self, hass: HomeAssistant, request: TimedRequest, targets: list[Target]) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            return await set_with_timer(self, target, {"on": False, "toggle_after": request.duration_s})

        return await self.gather(hass, targets, send)
