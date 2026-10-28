"""Zigbee2MQTT move: brightness and saturation published as an end point with a transition, hue as a rate move."""

import json
import logging
from dataclasses import dataclass
from statistics import mean
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import topic, z2m_address
from .bridge import has_feature
from .members import member_lights
from .xy_writeback import write_back_xy
from ...actions.move import UP, MoveRequest
from ...core import transition
from ...core.adapter import Adapter
from ...core.dispatcher import EMPTY_GROUP
from ...core.models import EntityResult, Status, Target
from ...core.runtime import Job, get_runtime
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, SATURATION, TransitionCache

_LOGGER = logging.getLogger(__name__)

# Z2M reads a light back within 0.7 s of a stop, and once a fade has run its published end value is right.
SETTLE_SECONDS = 2.0
# The smallest brightness or saturation step a bulb makes (1/254), in percent.
MIN_STEP = 100 / 254
# A hue move's rate is in steps of 1/254 of the cycle per second, 1 to 254, so a cycle takes 1 to 254 s.
MIN_CYCLE_S, MAX_CYCLE_S = 1.0, 254.0
# The end read-back, after the fade has run: a live read mid-fade may have overwritten Z2M's published end value.
END_READ_S = 1.0
COLOR_HS = "color_hs"  # the Z2M feature a hue or saturation move needs


def transition_cache(hass: HomeAssistant) -> TransitionCache:
    return transition.transition_cache(hass, "zigbee2mqtt", lambda: TransitionCache(SETTLE_SECONDS))


def hue_moves(hass: HomeAssistant) -> set[str]:
    """The lights a hue move of ours is cycling: it runs until a stop, so it has no transition to predict."""
    return get_runtime(hass).integration_state.setdefault("zigbee2mqtt_hue_moves", set())


def read_back_key(target: Target) -> str:
    """The key a target's end read-back is scheduled under, which its next move or stop replaces."""
    return f"zigbee2mqtt:move:{target.entity_id}"


async def lights_of(hass: HomeAssistant, target: Target) -> list[Target]:
    return await member_lights(hass, target) if target.is_group else [target]


def reported_brightness(light: Target) -> float:
    """HA's brightness in percent, 0 while off: a move from off starts at the bottom."""
    brightness = light.state.attributes.get("brightness") if light.state and light.state.state == "on" else None
    return brightness / 255 * 100 if brightness is not None else 0.0


def light_brightness(cache: TransitionCache, light: Target) -> float:
    return cache.value(light.entity_id, BRIGHTNESS, reported_brightness(light))


def lit(cache: TransitionCache, lights: list[Target]) -> list[Target]:
    """The lights that are on, or predicted above 0 %: Z2M publishes off at the start of a soft off."""
    return [
        light
        for light in lights
        if (light.state and light.state.state == "on") or cache.value(light.entity_id, BRIGHTNESS, 0.0) > 0
    ]


def hs_color(light: Target) -> tuple[float, float] | None:
    return light.state.attributes.get("hs_color") if light.state else None


async def publish(hass: HomeAssistant, mqtt_topic: str, payload: dict) -> None:
    await hass.services.async_call(
        "mqtt", "publish", {"topic": mqtt_topic, "payload": json.dumps(payload)}, blocking=True
    )


@dataclass(frozen=True, slots=True)
class Fade:
    """One attribute's fade: the payload published, each moving light's start and end, and how long it runs."""

    attribute: str
    payload: dict
    starts: dict[str, float]
    ends: dict[str, float]
    duration: float


class Z2MMove(Adapter[MoveRequest]):
    """Publish each attribute's limit (or range end) with a transition for the distance left; the bulb runs the fade.

    Brightness and saturation are separate publishes, each with its own transition: the bulb runs them independently.
    Predictions live per light and attribute (the core transition cache), so a move after a stop continues from where
    the light halted. A group gets one publish per attribute to its group topic, so its members fade together; each
    member's transition is recorded from its own start, and the group's start is the mean of its lit members.

    Up turns the light on. Down to 0 % is Z2M's soft off, state OFF with the transition, which keeps the level for the
    next plain on. Saturation is written as a color, the light's current hue with the end saturation, and moves only lit
    lights. Hue is Z2M's hue_move, a cycle at a rate the bulb runs until a stop; a sweep_time outside 1-254 s is
    clamped, with clamped_to. Hue and saturation are dropped on a light whose Z2M definition lacks color_hs. An
    attribute already at or past its limit is left out, and a move with nothing left to make is unchanged with at_limit;
    one with only lights that are off to move is unchanged with off.

    Z2M publishes the end value at once. Once a fade has run, its attributes are read back, and a saturation move's
    color brought in line (xy_writeback), so HA ends right even after a live read mid-fade.
    """

    action: ClassVar[str] = "move"
    integration: ClassVar[str] = "zigbee2mqtt"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        domains=frozenset({"light"}),
        # Color temperature is left out: no command halts a Hue bulb's color temperature fade without a visible jump.
        fields=frozenset({"brightness", "brightness_limit", "saturation", "saturation_limit", "hue"}),
        native_groups=True,
    )

    def supports(self, hass: HomeAssistant, request: MoveRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if topic(target, "set") is None:
            return "not_addressable"
        return None

    async def execute(self, hass: HomeAssistant, request: MoveRequest, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)

        async def send(target: Target) -> EntityResult:
            if not (lights := await lights_of(hass, target)):
                return self.result(target, Status.UNSUPPORTED, detail=EMPTY_GROUP)
            dropped = await lacked(hass, request, lights)
            move = request.without(dropped)
            if move.nothing_to_do():
                return self.result(target, Status.UNCHANGED, detail="fields_dropped")
            outcomes = plan(cache, move, target, lights)
            if not (made := [outcome for outcome in outcomes if not isinstance(outcome, str)]):
                # A light that's off explains a move having nothing to do, whatever else is at its limit.
                detail = "off" if "off" in outcomes else outcomes[0]
                return self.result(target, Status.UNCHANGED, detail=detail)
            clamped_to = await start(hass, cache, target, lights, made)
            return self.result(
                target, Status.SENT, clamped_to=clamped_to, detail="fields_dropped" if dropped else None
            )

        return await self.gather(hass, targets, send)


type HueMove = tuple[int, float | None]  # hue_move's signed rate, and the sweep_time used where it was clamped


def plan(cache: TransitionCache, move: MoveRequest, target: Target, lights: list[Target]) -> list[Fade | HueMove | str]:
    """Each attribute's fade or hue move, or why it has none to make."""
    outcomes: list[Fade | HueMove | str] = []
    if move.brightness:
        outcomes.append(brightness_fade(cache, move, lights))
    if move.saturation:
        outcomes.append(saturation_fade(cache, move, target, lights))
    if move.hue:
        outcomes.append(hue_rate(move) if move.brightness == UP or lit(cache, lights) else "off")
    return outcomes


async def start(
    hass: HomeAssistant, cache: TransitionCache, target: Target, lights: list[Target], made: list[Fade | HueMove]
) -> float | None:
    """Publish each fade and hue move, recording them, and schedule the end read-backs; the clamped sweep_time."""
    set_topic = topic(target, "set")
    clamped_to = None
    reads: list[tuple[float, Job]] = []
    for outcome in made:
        if isinstance(outcome, Fade):
            async with cache.recording((light_id, outcome.attribute) for light_id in outcome.starts):
                for light_id, begin in outcome.starts.items():
                    cache.moving(light_id, outcome.attribute, begin, outcome.ends[light_id], outcome.duration)
                await publish(hass, set_topic, outcome.payload)
            reads.append((outcome.duration + END_READ_S, end_read(hass, target, lights, outcome.attribute)))
        else:
            rate, clamped_to = outcome
            await publish(hass, set_topic, {"hue_move": rate})
            hue_moves(hass).update(light.entity_id for light in lights)
    if reads:
        get_runtime(hass).schedule(hass, read_back_key(target), reads)
    return clamped_to


async def lacked(hass: HomeAssistant, request: MoveRequest, lights: list[Target]) -> frozenset[str]:
    """Hue and saturation, with its limit, where a light's Z2M definition lacks color_hs, which the move drops."""
    color = request.fields_present() & {"hue", "saturation", "saturation_limit"}
    if not color or await has_feature(hass, [z2m_address(light.device) for light in lights], COLOR_HS):
        return frozenset()
    return color


def brightness_fade(cache: TransitionCache, request: MoveRequest, lights: list[Target]) -> Fade | str:
    """The brightness fade toward the limit; off down with nothing lit, at_limit when there is none left to make."""
    up = request.brightness == UP
    limit = request.brightness_limit if request.brightness_limit is not None else (100.0 if up else 0.0)
    starts = {light.entity_id: light_brightness(cache, light) for light in lights}
    lit_lights = lit(cache, lights)
    if not up and not lit_lights:
        return "off"
    # Up turns every light on, so the off ones fade in from the bottom; other moves pass them by.
    moving = [light.entity_id for light in (lights if up else lit_lights)]
    current = mean(starts[light.entity_id] for light in lit_lights or lights)
    if (limit - current if up else current - limit) < MIN_STEP:
        return "at_limit"
    duration = abs(limit - current) / 100 * request.sweep_time
    transition_s = round(duration, 1)
    if limit == 0:
        payload = {"state": "OFF", "transition": transition_s}
    else:
        payload = {"brightness": max(1, round(limit / 100 * 254)), "transition": transition_s}
        payload = {"state": "ON", **payload} if up else payload
    moving_starts = {light_id: starts[light_id] for light_id in moving}
    return Fade(BRIGHTNESS, payload, moving_starts, dict.fromkeys(moving, limit), duration)


def saturation_fade(cache: TransitionCache, request: MoveRequest, target: Target, lights: list[Target]) -> Fade | str:
    """The saturation fade toward the limit at the current hue; off with no lit light in color, at_limit when there is
    none left to make.

    Written as a color: with Z2M's hue_native_control on, the bulb fades in xy and holds its hue, and Z2M publishes the
    end as xy, which HA takes.
    """
    if not (movers := [light for light in lit(cache, lights) if hs_color(light) is not None]):
        return "off"
    up = request.saturation == UP
    limit = request.saturation_limit if request.saturation_limit is not None else (100.0 if up else 0.0)
    starts = {light.entity_id: cache.value(light.entity_id, SATURATION, hs_color(light)[1]) for light in movers}
    current = mean(starts.values())
    if (limit - current if up else current - limit) < MIN_STEP:
        return "at_limit"
    hue = (hs_color(target) or hs_color(movers[0]))[0]
    duration = abs(limit - current) / 100 * request.sweep_time
    payload = {"color": {"hue": round(hue, 1), "saturation": round(limit, 1)}, "transition": round(duration, 1)}
    return Fade(SATURATION, payload, starts, dict.fromkeys(starts, limit), duration)


def hue_rate(request: MoveRequest) -> HueMove:
    """hue_move's signed rate for the sweep_time, a full cycle, and the sweep_time used where it had to be clamped.

    Clamped, not refused: the call's value lies outside what the bulb can do, as an out-of-range duration does. Rounding
    the rate inside the range isn't reported.
    """
    cycle = min(max(request.sweep_time, MIN_CYCLE_S), MAX_CYCLE_S)
    rate = min(max(round(254 / cycle), 1), 254)
    return (rate if request.hue == UP else -rate), (cycle if cycle != request.sweep_time else None)


def end_read(hass: HomeAssistant, target: Target, lights: list[Target], attribute: str) -> Job:
    """The read-back once a fade has run: each light's state and brightness, or the target's color in line."""

    async def read() -> None:
        if attribute == SATURATION:
            await write_back_xy(hass, target, silent=True)
            return
        for light in lights:
            try:
                await publish(hass, topic(light, "get"), {"state": "", "brightness": ""})
            except Exception as err:  # noqa: BLE001 - a failed read leaves HA's state stale, nothing more
                _LOGGER.debug("End read-back for %s failed: %s", light.entity_id, err)

    return read
