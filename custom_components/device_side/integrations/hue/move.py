"""Hue move: a write per attribute to the light or room, with the end point and a duration the bridge runs alone."""

from dataclasses import dataclass
from statistics import mean
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.util.color import color_temperature_kelvin_to_mired

from .bridge import bridge_api, controller, resource_id
from .report_filter import report_filter
from .transition_cache import (
    BRIGHTNESS,
    COLOR_TEMP,
    MIN_BRIGHTNESS_STEP,
    MIN_MIREK_STEP,
    TransitionCache,
    transition_cache,
)
from ...actions.move import UP, WARMER, MoveRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from aiohue.v2 import HueBridgeV2
    from aiohue.v2.controllers.groups import GroupedLightController
    from aiohue.v2.controllers.lights import LightsController
    from aiohue.v2.models.grouped_light import GroupedLight
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


def light_mirek(cache: TransitionCache, light: Light) -> float:
    """A light's predicted color temperature in mirek; read only for a light in color temperature mode."""
    return cache.value(light.id, COLOR_TEMP, light.color_temperature.mirek)


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


class HueMove(Adapter[MoveRequest]):
    """Write each attribute's limit (or range end) with a duration for the distance left; the bridge runs the fade.

    Brightness and color temperature are separate writes, each with its own duration: the bridge runs them
    independently (Tested behavior in docs/integrations.md). Predictions live per light and attribute
    (transition_cache), so a move after a stop continues from where the light halted. A room is moved with one
    grouped_light write per attribute, so its lights converge on the end point together; each light's transition is
    recorded from its own start, and the room's start is the average of its lit lights, so moving one light mid
    room-move starts from where it really is. A room's color temperature heads for its end within the widest range
    among its lights, each light stopping at the edge of its own.

    Up turns the light on. Down to 0 % is a plain soft off, on: false with the duration and no brightness, so the
    bridge keeps the stored brightness for the next plain on. Color temperature moves only lit lights, so without
    brightness up a light or room with nothing lit is unchanged with off, and a light in color (xy) mode is left alone
    with not_in_color_temp_mode. An attribute the bridge says the light can't move is dropped. An attribute already
    at or past its limit is left out, and a move with nothing left to make is unchanged with at_limit and nothing is
    sent. With predicted_state on, HA holds the start brightness while the fade runs and shows the end once it has
    (report_filter); color temperature shows what the bridge reports.
    """

    action: ClassVar[str] = "move"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        fields=frozenset({"brightness", "brightness_limit", "color_temp", "color_temp_limit"}),
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

        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            writer = controller(api, target)
            rid = resource_id(target)
            if (resource := writer.get(rid)) is None:
                return self.result(target, Status.REJECTED, detail="not_on_bridge")
            lights = api.groups.grouped_light.get_lights(rid) if target.is_group else [resource]
            dropped = lacked(request, resource, lights)
            move = request.without(dropped)
            fades: list[Fade | str] = []
            if move.brightness:
                fades.append(brightness_fade(cache, move, target, api))
            if move.color_temp:
                fades.append(color_temp_fade(cache, move, lights))
            if not (made := [fade for fade in fades if isinstance(fade, Fade)]):
                # A light that's off explains a brightness move down having nothing to do too.
                detail = "off" if "off" in fades else fades[0] if fades else "fields_dropped"
                return self.result(target, Status.UNCHANGED, detail=detail)
            reports = report_filter(hass, target)
            for fade in made:
                write = fade_write(writer, rid, fade, move.brightness == UP)
                async with cache.recording((light_id, fade.attribute) for light_id in fade.starts):
                    for light_id, start in fade.starts.items():
                        cache.moving(light_id, fade.attribute, start, fade.ends[light_id], fade.duration)
                    await write
                reports.fading(fade.attribute, fade.ends, fade.duration)
            return self.result(target, Status.SENT, detail="fields_dropped" if dropped else None)

        return await self.gather(hass, targets, send)


def tunable(cache: TransitionCache, request: MoveRequest, lights: list[Light]) -> list[Light]:
    """The lights a color temperature move changes: up turns every light on, so they all move; other moves pass the
    off ones by."""
    lights = [light for light in lights if light.color_temperature]
    return lights if request.brightness == UP else lit(cache, lights)


def lacked(request: MoveRequest, resource: Light | GroupedLight, lights: list[Light]) -> frozenset[str]:
    """The attributes the bridge says the light or room can't move, with their limits, which the move drops."""
    lacked: set[str] = set()
    if resource.dimming is None:
        lacked |= {"brightness", "brightness_limit"}
    if not any(light.color_temperature for light in lights):
        lacked |= {"color_temp", "color_temp_limit"}
    return request.fields_present() & lacked


def fade_write(writer: LightsController | GroupedLightController, rid: str, fade: Fade, up: bool) -> Awaitable:
    transition_time = round(fade.duration * 1000)
    if fade.attribute == COLOR_TEMP:
        return writer.set_state(rid, color_temp=round(fade.target), transition_time=transition_time)
    if fade.target == 0:
        return writer.set_state(rid, on=False, transition_time=transition_time)
    return writer.set_state(rid, on=True if up else None, brightness=fade.target, transition_time=transition_time)


def brightness_fade(cache: TransitionCache, request: MoveRequest, target: Target, api: HueBridgeV2) -> Fade | str:
    """The brightness fade toward the limit, or at_limit when there is none left to make."""
    up = request.brightness == UP
    limit = request.brightness_limit if request.brightness_limit is not None else (100.0 if up else 0.0)
    if target.is_group:
        lights = room_lights(api, target)
        starts = {light.id: light_brightness(cache, light) for light in lights}
        # Up turns every light on, so the off ones fade in from the bottom; other moves pass them by.
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


def color_temp_fade(cache: TransitionCache, request: MoveRequest, lights: list[Light]) -> Fade | str:
    """The color temperature fade toward the limit within the widest range among the lights, each light ending at the
    edge of its own; off with no light to move, not_in_color_temp_mode while any is in color (xy) mode, at_limit when
    there is none left to make. Mirek rises as the light warms."""
    if not (movers := tunable(cache, request, lights)):
        return "off"
    if not all(light.color_temperature.mirek_valid for light in movers):
        return "not_in_color_temp_mode"
    warmer = request.color_temp == WARMER
    schemas = {light.id: light.color_temperature.mirek_schema for light in movers}
    low = min(schema.mirek_minimum for schema in schemas.values())
    high = max(schema.mirek_maximum for schema in schemas.values())
    if request.color_temp_limit is not None:
        target = min(max(color_temperature_kelvin_to_mired(request.color_temp_limit), low), high)
    else:
        target = high if warmer else low
    starts = {light.id: light_mirek(cache, light) for light in movers}
    current = mean(starts[light.id] for light in lit(cache, movers) or movers)
    if (target - current if warmer else current - target) < MIN_MIREK_STEP:
        return "at_limit"
    duration = abs(target - current) / max(high - low, 1) * request.sweep_time
    ends = {
        light_id: min(max(target, schema.mirek_minimum), schema.mirek_maximum) for light_id, schema in schemas.items()
    }
    return Fade(COLOR_TEMP, target, starts, ends, duration)
