"""Hue raise_brightness and lower_brightness: one brightness write to the light or room, with the end point and a
duration the bridge runs alone."""

from dataclasses import dataclass
from statistics import mean
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant

from .bridge import bridge_api, controller, resource_id
from .report_filter import report_filter
from .transition_cache import MIN_BRIGHTNESS_STEP, transition_cache
from ...actions.ramp import RampRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, TransitionCache

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from aiohue.v2 import HueBridgeV2
    from aiohue.v2.controllers.groups import GroupedLightController
    from aiohue.v2.controllers.lights import LightsController
    from aiohue.v2.models.light import Light


def reported_brightness(target: Target) -> float:
    """HA's brightness for the target in percent, 0 while off: a move from off starts at the bottom."""
    brightness = target.state.attributes.get("brightness") if target.state else None
    return brightness / 255 * 100 if brightness is not None else 0.0


def room_lights(api: HueBridgeV2, target: Target) -> list[Light]:
    """The room's lights that dim, hidden ones included: the bridge fades them all."""
    return [light for light in api.groups.grouped_light.get_lights(resource_id(target)) if light.dimming]


def light_brightness(cache: TransitionCache, light: Light) -> float:
    """A room light's predicted brightness in percent, 0 while off."""
    return cache.value(light.id, BRIGHTNESS, light.dimming.brightness if light.on.on else 0.0)


def lit(cache: TransitionCache, lights: list[Light]) -> list[Light]:
    """The lights that are on, or predicted above 0 %: aiohue hears a light turn on late, and a soft off reports off
    at its start."""
    return [light for light in lights if light.on.on or cache.value(light.id, BRIGHTNESS, 0.0) > 0]


def in_soft_off(cache: TransitionCache, light_id: str) -> bool:
    """Whether a move of ours is still fading the light to off, which the bridge won't take a dimming stop for."""
    return (transition := cache.running(light_id, BRIGHTNESS)) is not None and transition.target == 0


@dataclass(frozen=True, slots=True)
class Fade:
    """One attribute's fade: the value written, each moving light's start and end, and how long the bridge takes."""

    attribute: str
    target: float
    starts: dict[str, float]
    ends: dict[str, float]
    duration: float


class HueBrightnessFade(Adapter[RampRequest]):
    """Write the brightness limit (or range end) with a duration for the distance left; the bridge runs the fade.

    Predictions live per light (transition_cache), so a move after a stop continues from where the light halted. A
    room is moved with one grouped_light write, so its lights converge on the end point together; each light's
    transition is recorded from its own start, and the room's start is the average of its lit lights, so moving one
    light mid room-move starts from where it really is.

    Raising turns the light on. Lowering to 0 % is a plain soft off, on: false with the duration and no brightness, so
    the bridge keeps the stored brightness for the next plain on. A light the bridge says can't dim is unchanged with
    fields_dropped. A light already at or past the limit is unchanged with at_limit and nothing is sent. With
    predicted_state on, HA holds the start brightness while the fade runs and shows the end once it has (report_filter).
    """

    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        fields=frozenset({BRIGHTNESS}),
        options=frozenset({"predicted_state"}),
        native_groups=True,
    )

    def supports(self, hass: HomeAssistant, request: RampRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if bridge_api(target) is None:
            return "bridge_v1"
        return None

    async def execute(self, hass: HomeAssistant, request: RampRequest, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)

        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            writer = controller(api, target)
            rid = resource_id(target)
            if (resource := writer.get(rid)) is None:
                return self.result(target, Status.REJECTED, detail="not_on_bridge")
            if resource.dimming is None:
                return self.result(target, Status.UNCHANGED, detail="fields_dropped")
            if isinstance(fade := brightness_fade(cache, request, target, api), str):
                return self.result(target, Status.UNCHANGED, detail=fade)
            write = fade_write(writer, rid, fade, request.up)
            async with cache.recording((light_id, fade.attribute) for light_id in fade.starts):
                for light_id, start in fade.starts.items():
                    cache.moving(light_id, fade.attribute, start, fade.ends[light_id], fade.duration)
                await write
            report_filter(hass, target).fading(fade.attribute, fade.ends, fade.duration)
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)


def fade_write(writer: LightsController | GroupedLightController, rid: str, fade: Fade, up: bool) -> Awaitable:
    transition_time = round(fade.duration * 1000)
    if fade.target == 0:
        return writer.set_state(rid, on=False, transition_time=transition_time)
    return writer.set_state(rid, on=True if up else None, brightness=fade.target, transition_time=transition_time)


def brightness_fade(cache: TransitionCache, request: RampRequest, target: Target, api: HueBridgeV2) -> Fade | str:
    """The brightness fade toward the limit, or at_limit when there is none left to make."""
    up, limit = request.up, request.end()
    if target.is_group:
        lights = room_lights(api, target)
        starts = {light.id: light_brightness(cache, light) for light in lights}
        # Raising turns every light on, so the off ones fade in from the bottom; lowering passes them by.
        lit_lights = lit(cache, lights)
        moving = [light.id for light in (lights if up else lit_lights)]
        current = mean(starts[light.id] for light in lit_lights or lights) if lights else 0.0
    else:
        rid = resource_id(target)
        starts = {rid: cache.value(rid, BRIGHTNESS, reported_brightness(target))}
        moving, current = [rid], starts[rid]
    if (limit - current if up else current - limit) < MIN_BRIGHTNESS_STEP:
        return "at_limit"
    duration = abs(limit - current) / 100 * request.sweep_time
    return Fade(
        BRIGHTNESS, limit, {light_id: starts[light_id] for light_id in moving}, dict.fromkeys(moving, limit), duration
    )
