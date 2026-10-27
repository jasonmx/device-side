"""Hue stop: halt the bridge's fade and remember where it halted, which the bridge reports late or never."""

import asyncio
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .bridge import bridge_api, controller, resource_id
from .move import end_echo, in_soft_off, light_brightness, lit, reported_brightness, room_lights
from .report_filter import report_filter
from .transition_cache import BRIGHTNESS, transition_cache
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope


class HueStop(Adapter[Request]):
    """Send a dimming stop to the light or room and record the predicted brightness as where it halted.

    The bridge refuses a dimming stop during a soft off, so a light our move is fading to off is cut instead with
    on: true and its predicted brightness, no duration. A room in one is cut light by light, each at its own
    prediction. A room's halt is recorded per lit light, where predictions live. A light or room with nothing lit
    (off, or fading off from elsewhere, which can't be predicted) is unchanged with off and nothing is sent. With
    predicted_state on, HA is shown the halt at once (report_filter).
    """

    action: ClassVar[str] = "stop"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True, options=frozenset({"predicted_state"}), native_groups=True
    )

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if bridge_api(target) is None:
            return "bridge_v1"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)

        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            writer = controller(api, target)
            rid = resource_id(target)
            if (resource := writer.get(rid)) is None:
                return self.result(target, Status.REJECTED, detail="not_on_bridge")
            if resource.dimming is None:
                return self.result(target, Status.UNSUPPORTED, detail="not_dimmable")
            reports = report_filter(hass, target)
            if target.is_group:
                halts = {light.id: light_brightness(cache, light) for light in lit(cache, room_lights(api, target))}
            elif lit(cache, [resource]):
                halts = {rid: cache.value(rid, BRIGHTNESS, reported_brightness(target))}
            else:
                halts = {}
            if not halts:
                return self.result(target, Status.UNCHANGED, detail="off")
            if fading_off := {light_id for light_id in halts if in_soft_off(cache, light_id)}:
                # The cut reports on and its brightness; a dimming stop reports nothing.
                echoes = {
                    light_id: end_echo(cache, api.lights.get(light_id), halts[light_id], up=True)
                    for light_id in fading_off
                }
                write = asyncio.gather(
                    *(
                        api.lights.set_state(light_id, on=True, brightness=value)
                        if light_id in fading_off
                        else api.lights.set_dimming_delta(light_id)
                        for light_id, value in halts.items()
                    )
                )
                await cache.write_armed(echoes, 0.0, write)
            else:
                await writer.set_dimming_delta(rid)
            for light_id, value in halts.items():
                cache.stopped(light_id, BRIGHTNESS, value)
            reports.halted(halts)
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)
