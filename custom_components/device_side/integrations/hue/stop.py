"""Hue stop: halt the bridge's fades and remember where they halted, which the bridge reports late or never."""

import asyncio
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant

from .bridge import bridge_api, controller, put, resource_id, stops
from .move import in_soft_off, light_brightness, light_mirek, lit, reported_brightness, room_lights
from .report_filter import report_filter
from .transition_cache import BRIGHTNESS, COLOR_TEMP, TransitionCache, transition_cache
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from aiohue.v2 import HueBridgeV2
    from aiohue.v2.controllers.groups import GroupedLightController
    from aiohue.v2.controllers.lights import LightsController


class HueStop(Adapter[Request]):
    """Send a dimming stop to the light or room, with a color temperature stop where a move of ours changed it, and
    record the predicted values as where it halted. Both stops go in one write.

    The bridge refuses a dimming stop during a soft off, so a light our move is fading to off is cut instead with
    on: true and its predicted brightness, no duration (and its color temperature stop). A room in one is cut light by
    light, each at its own prediction. A room's halt is recorded per lit light, where predictions live. A light or room
    with nothing lit (off, or fading off from elsewhere, which can't be predicted) is unchanged with off and nothing is
    sent. With predicted_state on, HA is shown the halted brightness at once (report_filter).
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
                lights = lit(cache, room_lights(api, target))
                brightness = {light.id: light_brightness(cache, light) for light in lights}
            else:
                lights = lit(cache, [resource])
                brightness = {rid: cache.value(rid, BRIGHTNESS, reported_brightness(target))} if lights else {}
            if not brightness:
                return self.result(target, Status.UNCHANGED, detail="off")
            # Color temperature only where a move of ours changed it: a stop of a light that isn't fading is a no-op.
            color_temp = {light.id: light_mirek(cache, light) for light in lights if cache.tracks(light.id, COLOR_TEMP)}
            halts = {BRIGHTNESS: brightness, COLOR_TEMP: color_temp}
            write = stop_write(cache, api, writer, rid, halts)
            async with cache.recording(
                (light_id, attribute) for attribute, values in halts.items() for light_id in values
            ):
                for attribute, values in halts.items():
                    for light_id, value in values.items():
                        cache.stopped(light_id, attribute, value)
                await write
            for attribute, values in halts.items():
                if values:
                    reports.halted(attribute, values)
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)


def stop_write(
    cache: TransitionCache,
    api: HueBridgeV2,
    writer: LightsController | GroupedLightController,
    rid: str,
    halts: dict[str, dict[str, float]],
) -> Awaitable:
    """One write to the light or room, or one per light while any is in our soft off, which the bridge refuses a
    dimming stop for: on: true at its predicted brightness ends it there instead."""
    brightness, color_temp = halts[BRIGHTNESS], halts[COLOR_TEMP]
    if not (fading_off := {light_id for light_id in brightness if in_soft_off(cache, light_id)}):
        return put(api, writer, rid, stops([BRIGHTNESS, *([COLOR_TEMP] if color_temp else [])]))
    return asyncio.gather(
        *(
            put(
                api,
                api.lights,
                light_id,
                (
                    {"on": {"on": True}, "dimming": {"brightness": value}}
                    if light_id in fading_off
                    else stops([BRIGHTNESS])
                )
                | stops([COLOR_TEMP] if light_id in color_temp else []),
            )
            for light_id, value in brightness.items()
        )
    )
