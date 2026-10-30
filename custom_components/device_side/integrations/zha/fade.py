"""ZHA raise and lower: brightness and saturation sent as an end point with a transition, hue as an EnhancedMoveHue
rate, through zha.issue_zigbee_cluster_command (or one zha.issue_zigbee_group_command for a ZHA group's members). Each
action's adapter is a ZHARamp."""

import asyncio
import logging
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, ClassVar

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.util.color import color_hs_to_xy

from . import zcl
from .addressing import address, unsupported_reason, via_zha_group
from .groups import light_members
from ...actions.ramp import HUE, RampRequest
from ...core import transition
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.runtime import Job, get_runtime
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, SATURATION, TransitionCache, hs_color, light_brightness, lit

_LOGGER = logging.getLogger(__name__)

# A refresh after a fade or a stop reads the bulb's real value, so a prediction is needed only until then.
SETTLE_SECONDS = 2.0
# The smallest brightness or saturation step a bulb makes (1/254), in percent.
MIN_STEP = 100 / 254
# EnhancedMoveHue's rate is in steps of 1/65536 of the cycle per second, 1 to 65535, so a cycle takes 1 to 65535 s.
MIN_CYCLE_S, MAX_CYCLE_S = 1.0, 65535.0
# The end refresh and the soft off's restore, after the fade has run: the bulb reads its end within it (probe 13f).
END_REFRESH_S = 1.0
# A ZCL transition is a uint16 in tenths of a second; 0xFFFF means the bulb's default.
_MAX_TENTHS = 0xFFFE
_MOVE_UP, _MOVE_DOWN = 0x01, 0x03
_COLOR_MODES = frozenset({"xy", "hs"})

type Command = tuple[int, int, dict[str, Any]]  # cluster, command, params in the command's positional order


def transition_cache(hass: HomeAssistant) -> TransitionCache:
    return transition.transition_cache(hass, "zha", lambda: TransitionCache(SETTLE_SECONDS))


def hue_moves(hass: HomeAssistant) -> set[str]:
    """The lights a hue move of ours is cycling: it runs until a stop, so it has no transition to predict."""
    return get_runtime(hass).integration_state.setdefault("zha_hue_moves", set())


def end_key(light: Target, attribute: str) -> str:
    """The key an attribute's end refresh (and a soft off's restore) is scheduled under, which the attribute's next
    move, or a stop, replaces."""
    return f"zha:ramp:{light.entity_id}:{attribute}"


def units(hass: HomeAssistant, targets: list[Target]) -> list[tuple[int | None, list[Target]]]:
    """The targets as one unit per ZHA group they were expanded from, with its Zigbee group ID, then one per other
    target, with None."""
    groups: dict[int, list[Target]] = {}
    singles: list[tuple[int | None, list[Target]]] = []
    for target in targets:
        if (gid := via_zha_group(hass, target)) is not None:
            groups.setdefault(gid, []).append(target)
        else:
            singles.append((None, [target]))
    return [*groups.items(), *singles]


def has_color(light: Target) -> bool:
    modes = light.state.attributes.get("supported_color_modes") if light.state else None
    return bool(set(modes or ()) & _COLOR_MODES)


def drops_while_off(light: Target) -> bool:
    return light.device is not None and light.device.model in zcl.DROPS_WHILE_OFF


async def send(
    hass: HomeAssistant, gid: int | None, movers: list[Target], command: Command, context: Context | None
) -> None:
    """One groupcast when the movers are every light the group holds, so they move in lockstep; else one command each.

    A groupcast reaches every member, so one that isn't moving (off, on a move that passes it by) gets its own command
    instead: a soft off sent to an off light would still drop its stored level.
    """
    cluster_id, command_id, params = command
    if gid is not None and light_members(hass, gid) <= {light.entity_id for light in movers}:
        await zcl.group_command(hass, gid, cluster_id, command_id, list(params.values()), context)
        return
    for light in movers:
        await zcl.command(hass, address(light.entry.unique_id), cluster_id, command_id, params, context)


async def refresh(hass: HomeAssistant, light: Target, context: Context | None) -> None:
    try:
        await hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": light.entity_id}, blocking=True, context=context
        )
    except Exception as err:  # noqa: BLE001 - a failed refresh leaves HA's state stale, nothing more
        _LOGGER.debug("update_entity for %s failed: %s", light.entity_id, err)


@dataclass(frozen=True, slots=True)
class Fade:
    """One attribute's fade: the command, each moving light's start and end, and how long it runs; the lights to put at
    the bottom first, and the level each soft-off light gets back once it reads off."""

    attribute: str
    command: Command
    movers: list[Target]
    starts: dict[str, float]
    ends: dict[str, float]
    duration: float
    presets: list[Target] = field(default_factory=list)
    restores: frozenset[str] = frozenset()  # the soft-off lights whose start level goes back, from starts


@dataclass(frozen=True, slots=True)
class HueMove:
    command: Command
    movers: list[Target]
    clamped_to: float | None  # the sweep_time used, where it had to be clamped


def ramp_scope(attribute: str) -> AdapterScope:
    return AdapterScope(
        experimental=True, domains=frozenset({"light"}), fields=frozenset({attribute}), max_concurrency=2
    )


class ZHARamp(Adapter[RampRequest]):
    """Send the limit (or range end) with a transition for the distance left; the bulb runs the fade.

    Brightness and saturation fades are separate calls, each with its own transition: the bulb runs them
    independently. Predictions live per light and attribute (the core transition cache), so a move after a stop
    continues from where the light halted. The dispatcher expands a ZHA group into its members; those from one group
    get one groupcast, so they fade together, each recorded from its own start, and the group's start is the mean of
    its lit members.

    Raising brightness is MoveToLevelWithOnOff, which turns the light on; a light that is off is first set to level 1
    with ExecuteIfOff, so it fades in from the bottom rather than its stored level. Lowering to a limit is MoveToLevel,
    which a light that is off ignores. Lowering to 0 is MoveToLevelWithOnOff to 0, which leaves the bulb at level 1;
    once it reads off, its start level goes back with ExecuteIfOff, so it stays off and comes back at its old level, as
    on Hue. Models that drop a level while off (zcl.DROPS_WHILE_OFF) get neither: they start a raise at their stored
    level, and come back on dim.

    Saturation is MoveToColor, the xy of the light's current hue at the end saturation, on lit lights in color. Hue is
    EnhancedMoveHue, a cycle the bulb runs until a stop, on lit lights whose ColorCapabilities report enhanced hue; a
    sweep_time outside 1-65535 s is clamped, with clamped_to. A group is unchanged with fields_dropped for hue if any
    member lacks it. A move with nothing left to make is unchanged with at_limit; one with only lights that are off to
    move is unchanged with off.

    Once a fade has run, each light is refreshed with update_entity: ZHA applies the bulb's brightness reports but never
    its color ones.
    """

    integration: ClassVar[str] = "zha"

    def supports(self, hass: HomeAssistant, request: RampRequest, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target)

    async def execute(self, hass: HomeAssistant, request: RampRequest, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)
        runs = [self._unit(hass, request, cache, gid, lights) for gid, lights in units(hass, targets)]
        return [result for batch in await asyncio.gather(*runs) for result in batch]

    async def _unit(
        self, hass: HomeAssistant, request: RampRequest, cache: TransitionCache, gid: int | None, lights: list[Target]
    ) -> list[EntityResult]:
        def each(status: Status, **kwargs) -> list[EntityResult]:
            return [self.result(light, status, **kwargs) for light in lights]

        if await lacks_hue(hass, request, lights):
            return each(Status.UNCHANGED, detail="fields_dropped")
        outcome = plan(cache, request, lights)
        if (
            isinstance(outcome, str)
            and request.attribute == BRIGHTNESS
            and any(cache.tracks(light.entity_id, BRIGHTNESS) for light in lights)
        ):
            # Nothing to do by the prediction, which a change made elsewhere can leave stale: ZHA applies the bulb's
            # brightness reports, so its state is right then. Plan again from it.
            for light in lights:
                cache.forget(light.entity_id, BRIGHTNESS)
            outcome = plan(cache, request, lights)
        if isinstance(outcome, str):
            return each(Status.UNCHANGED, detail=outcome)
        integration_limit, adapter_limit = self.limits(hass)
        try:
            async with integration_limit, adapter_limit:
                clamped_to = await start(hass, request.context, cache, gid, outcome)
        except Unauthorized:
            return each(Status.REJECTED, detail="admin_required")
        except Exception as err:  # noqa: BLE001 - as in gather(): one group's failure must not abort the room
            names = ", ".join(light.entity_id for light in lights)
            _LOGGER.warning("%s on zha failed for %s: %s", self.action, names, err)
            return each(Status.REJECTED, detail="error")
        moved = {light.entity_id for light in outcome.movers}
        return [
            self.result(light, Status.SENT, clamped_to=clamped_to)
            if light.entity_id in moved
            else self.result(light, Status.UNCHANGED, detail="off")
            for light in lights
        ]


def plan(cache: TransitionCache, request: RampRequest, lights: list[Target]) -> Fade | HueMove | str:
    """The attribute's fade or hue move, or why it has none to make."""
    if request.attribute == BRIGHTNESS:
        return brightness_fade(cache, request, lights)
    if request.attribute == SATURATION:
        return saturation_fade(cache, request, lights)
    return hue_move(request, movers) if (movers := lit(cache, lights)) else "off"


async def start(
    hass: HomeAssistant, context: Context | None, cache: TransitionCache, gid: int | None, outcome: Fade | HueMove
) -> float | None:
    """Send the fade, recording it, and schedule each light's end refresh, or send the hue move; the clamped
    sweep_time."""
    if isinstance(outcome, HueMove):
        await send(hass, gid, outcome.movers, outcome.command, context)
        hue_moves(hass).update(light.entity_id for light in outcome.movers)
        return outcome.clamped_to
    if outcome.attribute == SATURATION:
        hue_moves(hass).difference_update(outcome.starts)  # a color write ends the bulb's hue cycle
    async with cache.recording((light_id, outcome.attribute) for light_id in outcome.starts):
        recorded = {
            light_id: cache.moving(light_id, outcome.attribute, begin, outcome.ends[light_id], outcome.duration)
            for light_id, begin in outcome.starts.items()
        }
        # Unicast: each concerns one light's own stored level.
        for light in outcome.presets:
            bottom = {"level": 1, **zcl.execute_if_off(0)}
            await zcl.command(
                hass, address(light.entry.unique_id), zcl.LEVEL_CLUSTER, zcl.MOVE_TO_LEVEL, bottom, context
            )
        await send(hass, gid, outcome.movers, outcome.command, context)
    for light in outcome.movers:
        if outcome.attribute == BRIGHTNESS:
            hass.async_create_task(sync_to_bulb(hass, cache, light, outcome, recorded[light.entity_id]))
        restore = outcome.starts if light.entity_id in outcome.restores else None
        job = end_job(hass, light, restore, context)
        # Replaces the attribute's pending refresh and restore: those of the light's other attribute run on.
        get_runtime(hass).schedule(hass, end_key(light, outcome.attribute), [(outcome.duration + END_REFRESH_S, job)])
    return None


async def lacks_hue(hass: HomeAssistant, request: RampRequest, lights: list[Target]) -> bool:
    """Whether a hue move meets a light whose ColorCapabilities lack enhanced hue. The dispatcher already dropped
    saturation and hue from lights without color."""
    if request.attribute != HUE:
        return False
    for light in lights:
        if not await zcl.enhanced_hue(hass, address(light.entry.unique_id)):
            return True
    return False


def fade_seconds(distance: float, sweep_time: float) -> float:
    """How long a fade over `distance` percent takes at the sweep_time's speed, at most the longest ZCL transition: a
    longer fade runs at that, faster."""
    return min(distance / 100 * sweep_time, _MAX_TENTHS / 10)


def transition_tenths(duration: float) -> int:
    return round(duration * 10)


def brightness_fade(cache: TransitionCache, request: RampRequest, lights: list[Target]) -> Fade | str:
    """The brightness fade toward the limit; off lowering with nothing lit, at_limit when there is none left to make."""
    up, limit = request.up, request.end()
    starts = {light.entity_id: light_brightness(cache, light) for light in lights}
    lit_lights = lit(cache, lights)
    if not up and not lit_lights:
        return "off"
    # Raising turns every light on, so the off ones fade in from the bottom; lowering passes them by.
    movers = lights if up else lit_lights
    current = mean(starts[light.entity_id] for light in lit_lights or lights)
    if (limit - current if up else current - limit) < MIN_STEP:
        return "at_limit"
    duration = fade_seconds(abs(limit - current), request.sweep_time)
    tenths = transition_tenths(duration)
    presets: list[Target] = []
    restores: frozenset[str] = frozenset()
    if up:
        command_id, level = zcl.MOVE_TO_LEVEL_WITH_ON_OFF, zcl.level(limit)
        lit_ids = {light.entity_id for light in lit_lights}
        presets = [light for light in lights if light.entity_id not in lit_ids and not drops_while_off(light)]
    elif limit == 0:
        command_id, level = zcl.MOVE_TO_LEVEL_WITH_ON_OFF, 0
        restores = frozenset(light.entity_id for light in movers if not drops_while_off(light))
    else:
        command_id, level = zcl.MOVE_TO_LEVEL, zcl.level(limit)
    command = (zcl.LEVEL_CLUSTER, command_id, {"level": level, "transition_time": tenths})
    moving_starts = {light.entity_id: starts[light.entity_id] for light in movers}
    return Fade(
        BRIGHTNESS, command, movers, moving_starts, dict.fromkeys(moving_starts, limit), duration, presets, restores
    )


def saturation_fade(cache: TransitionCache, request: RampRequest, lights: list[Target]) -> Fade | str:
    """The saturation fade toward the limit at the current hue, as an xy fade; off with no lit light in color, at_limit
    when there is none left to make."""
    if not (movers := [light for light in lit(cache, lights) if hs_color(light) is not None]):
        return "off"
    up, limit = request.up, request.end()
    starts = {light.entity_id: cache.value(light.entity_id, SATURATION, hs_color(light)[1]) for light in movers}
    current = mean(starts.values())
    if (limit - current if up else current - limit) < MIN_STEP:
        return "at_limit"
    x, y = color_hs_to_xy(hs_color(movers[0])[0], limit)
    duration = fade_seconds(abs(limit - current), request.sweep_time)
    params = {"color_x": round(x * 65535), "color_y": round(y * 65535), "transition_time": transition_tenths(duration)}
    command = (zcl.COLOR_CLUSTER, zcl.MOVE_TO_COLOR, params)
    return Fade(SATURATION, command, movers, starts, dict.fromkeys(starts, limit), duration)


def hue_move(request: RampRequest, movers: list[Target]) -> HueMove:
    """EnhancedMoveHue at the rate for the sweep_time, a full cycle, and the sweep_time used where it had to be clamped.

    Clamped, not refused: the call's value lies outside what the bulb can do, as an out-of-range duration does. Rounding
    the rate inside the range isn't reported.
    """
    cycle = min(max(request.sweep_time, MIN_CYCLE_S), MAX_CYCLE_S)
    rate = min(max(round(65535 / cycle), 1), 65535)
    mode = _MOVE_UP if request.up else _MOVE_DOWN
    command = (zcl.COLOR_CLUSTER, zcl.ENHANCED_MOVE_HUE, {"move_mode": mode, "rate": rate})
    return HueMove(command, movers, cycle if cycle != request.sweep_time else None)


async def sync_to_bulb(
    hass: HomeAssistant, cache: TransitionCache, light: Target, fade: Fade, recorded: transition.Transition
) -> None:
    """Fit the recorded ramp to a CurrentLevel read taken just after the fade was sent.

    The bulb fades from its real level, which a change made elsewhere (one ZHA can't tell from the bulb's own reports)
    leaves the prediction blind to. The read is timed at the middle of its round trip and lies on the bulb's ramp, which
    ends at the sent end point at the sent end time, so the ramp's real start is solved for and the fade re-recorded
    from it: the next move, a stop and the soft off's restore then start from where the bulb really is. Sent first and
    read after, so a move starts with no added latency; a read after the fade's end, or after a newer move or a stop
    took over, changes nothing.
    """
    try:
        before = cache.clock()
        read = await zcl.read_attributes(hass, address(light.entry.unique_id), zcl.LEVEL_CLUSTER, (zcl.CURRENT_LEVEL,))
        at = (before + cache.clock()) / 2
        level = read[zcl.CURRENT_LEVEL] * 100 / 254
    except Exception as err:  # noqa: BLE001 - the prediction stands, as on the other integrations
        _LOGGER.debug("Level read after a fade was sent failed for %s: %s", light.entity_id, err)
        return
    elapsed = (at - recorded.started_at) / recorded.duration if recorded.duration > 0 else 1.0
    if elapsed >= 1 or cache.live(light.entity_id, BRIGHTNESS) is not recorded:
        return
    start = min(max((level - recorded.target * elapsed) / (1 - elapsed), 0.0), 100.0)
    fade.starts[light.entity_id] = start
    cache.moving(light.entity_id, BRIGHTNESS, start, recorded.target, recorded.duration, started_at=recorded.started_at)


def end_job(hass: HomeAssistant, light: Target, restore: dict[str, float] | None, context: Context | None) -> Job:
    """Once a fade has run: a soft off's restore of the light's start level (in restore, as last fitted), if the light
    reads off, then a refresh."""

    async def run() -> None:
        if restore is not None:
            try:
                addr = address(light.entry.unique_id)
                read = await zcl.read_attributes(hass, addr, zcl.ON_OFF_CLUSTER, (zcl.ON_OFF,))
                if not read[zcl.ON_OFF]:
                    params = {"level": zcl.level(restore[light.entity_id]), **zcl.execute_if_off(0)}
                    await zcl.command(hass, addr, zcl.LEVEL_CLUSTER, zcl.MOVE_TO_LEVEL, params, context)
            except Exception as err:  # noqa: BLE001 - the light stays off, and comes back on dim
                _LOGGER.warning("Restoring %s's level after a soft off failed: %s", light.entity_id, err)
        await refresh(hass, light, context)

    return run
