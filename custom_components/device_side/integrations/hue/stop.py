"""Hue stop: halt the bridge's fades and remember where they halted, which the bridge reports late or never."""

import asyncio
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant

from .bridge import bridge_api, controller, put, resource_id, stops
from .fade import in_soft_off, light_brightness, lit, reported_brightness, room_lights
from .report_filter import report_filter
from .transition_cache import transition_cache
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, TransitionCache

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from aiohue.v2 import HueBridgeV2
    from aiohue.v2.controllers.groups import GroupedLightController
    from aiohue.v2.controllers.lights import LightsController


class HueStop(Adapter[Request]):
    """Send a dimming stop to the light or room, and record the predicted brightness as where it halted.

    The bridge refuses a dimming stop during a soft off, so a light our move is fading to off is cut instead with
    on: true and its predicted brightness, no duration. A room in one is cut light by light, each at its own
    prediction. A room's halt is recorded per lit light, where predictions live. A light or room with nothing lit (off,
    or fading off from elsewhere, which can't be predicted) is unchanged with off and nothing is sent. With
    predicted_state on, HA is shown the halted brightness at once (report_filter).
    """

    action: ClassVar[str] = "stop"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True, options=frozenset({"predicted_state"}), native_groups=True
    )

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if (api := bridge_api(target)) is None:
            return "bridge_v1"
        if (resource := controller(api, target).get(resource_id(target))) is not None and resource.dimming is None:
            return "not_dimmable"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)

        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            writer = controller(api, target)
            rid = resource_id(target)
            if (resource := writer.get(rid)) is None:
                return self.result(target, Status.REJECTED, detail="not_on_bridge")
            reports = report_filter(hass, target)
            if target.is_group:
                lights = lit(cache, room_lights(api, target))
                brightness = {light.id: light_brightness(cache, light) for light in lights}
            else:
                lights = lit(cache, [resource])
                brightness = {rid: cache.value(rid, BRIGHTNESS, reported_brightness(target))} if lights else {}
            if not brightness:
                return self.result(target, Status.UNCHANGED, detail="off")
            write = stop_write(cache, api, writer, rid, brightness)
            async with cache.recording((light_id, BRIGHTNESS) for light_id in brightness):
                for light_id, value in brightness.items():
                    cache.stopped(light_id, BRIGHTNESS, value)
                await write
            reports.halted(BRIGHTNESS, brightness)
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)


def stop_write(
    cache: TransitionCache,
    api: HueBridgeV2,
    writer: LightsController | GroupedLightController,
    rid: str,
    brightness: dict[str, float],
) -> Awaitable:
    """One write to the light or room, or one per light while any is in our soft off, which the bridge refuses a
    dimming stop for: on: true at its predicted brightness ends it there instead."""
    if not (fading_off := {light_id for light_id in brightness if in_soft_off(cache, light_id)}):
        return put(api, writer, rid, stops([BRIGHTNESS]))
    return asyncio.gather(
        *(
            put(api, api.lights, light_id, cut(value) if light_id in fading_off else stops([BRIGHTNESS]))
            for light_id, value in brightness.items()
        )
    )


def cut(brightness: float) -> dict:
    """The PUT body that ends a soft off at this brightness, which the bridge takes in place of a dimming stop."""
    return {"on": {"on": True}, "dimming": {"brightness": brightness}}
