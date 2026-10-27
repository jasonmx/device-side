"""Hue move: one write per light or room, with the end point and a duration the bridge runs on its own."""

from statistics import mean
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant

from .bridge import bridge_api, controller, resource_id
from .report_filter import report_filter
from .transition_cache import BRIGHTNESS, MIN_BRIGHTNESS_STEP, REPORT_TOLERANCE, TransitionCache, transition_cache
from ...actions.move import UP, MoveRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope

if TYPE_CHECKING:
    from aiohue.v2 import HueBridgeV2
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


def end_echo(cache: TransitionCache, light: Light, limit: float, up: bool) -> dict[str, float | bool]:
    """What the bridge reports at the start of a move of the light to limit: only what changes is reported.

    A soft off writes no brightness, so it reports on: false alone. A move to the brightness the bridge already
    holds reports nothing. What it holds is its last report, which predicted_state may have kept from aiohue.
    """
    on = cache.bridge_value(light.id, "on", light.on.on)
    if limit == 0:
        return {"on": False} if on else {}
    echo: dict[str, float | bool] = {}
    if abs(cache.bridge_value(light.id, BRIGHTNESS, light.dimming.brightness) - limit) > REPORT_TOLERANCE:
        echo[BRIGHTNESS] = limit
    if up and not on:
        echo["on"] = True
    return echo


class HueMove(Adapter[MoveRequest]):
    """Write the brightness limit (or range end) with a duration for the distance left; the bridge runs the fade.

    Predictions live per light (transition_cache), so a move after a stop continues from where the light halted.
    A room is moved with one grouped_light write, so its lights converge on the end point together; each light's
    transition is recorded from its own start, and the room's start is the average of its lit lights, so moving
    one light mid room-move starts from where it really is. Up turns the light on. Down to 0 % is a plain soft off,
    on: false with the duration and no brightness, so the bridge keeps the stored brightness for the next plain on.
    A light or room already at or past its limit is unchanged with at_limit and nothing is sent. With predicted_state
    on, HA holds the start value while the fade runs and shows the end once it has (report_filter).
    """

    action: ClassVar[str] = "move"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        fields=frozenset({"brightness", "brightness_limit"}),
        options=frozenset({"predicted_state"}),
        native_groups=True,
    )

    def supports(self, hass: HomeAssistant, request: MoveRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if bridge_api(target) is None:
            return "bridge_v1"
        return None

    async def execute(self, hass: HomeAssistant, request: MoveRequest, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)
        up = request.brightness == UP
        limit = request.brightness_limit if request.brightness_limit is not None else (100.0 if up else 0.0)

        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            writer = controller(api, target)
            rid = resource_id(target)
            if (resource := writer.get(rid)) is None:
                return self.result(target, Status.REJECTED, detail="not_on_bridge")
            if resource.dimming is None:
                return self.result(target, Status.UNSUPPORTED, detail="fields_not_supported")
            reports = report_filter(hass, target)
            if target.is_group:
                lights = room_lights(api, target)
                starts = {light.id: light_brightness(cache, light) for light in lights}
                # Up turns every light on, so the off ones fade in from the bottom; other moves pass them by.
                lit_lights = lit(cache, lights)
                moving = {light.id: light for light in (lights if up else lit_lights)}
                current = mean(starts[light.id] for light in lit_lights or lights) if lights else 0.0
            else:
                starts = {rid: cache.value(rid, BRIGHTNESS, reported_brightness(target))}
                moving, current = {rid: resource}, starts[rid]
            if (limit - current if up else current - limit) < MIN_BRIGHTNESS_STEP:
                return self.result(target, Status.UNCHANGED, detail="at_limit")
            duration = abs(limit - current) / 100 * request.sweep_time
            transition_time = round(duration * 1000)
            if limit == 0:
                write = writer.set_state(rid, on=False, transition_time=transition_time)
            else:
                write = writer.set_state(
                    rid, on=True if up else None, brightness=limit, transition_time=transition_time
                )
            echoes = {light_id: end_echo(cache, light, limit, up) for light_id, light in moving.items()}
            await cache.write_armed(echoes, duration, write)
            for light_id in moving:
                cache.moving(light_id, BRIGHTNESS, starts[light_id], limit, duration)
            reports.fading(dict.fromkeys(moving, limit), duration)
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)
