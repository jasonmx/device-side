"""What a Hue light or room is doing mid-move, which the bridge doesn't report.

While a transition runs the bridge (and so HA) reports the end value at once, and after a stop mid-flight it reports
where the light halted late or not at all. Each move and stop is recorded here so the next move, stop or read starts
from the value the light is really at, which is what makes a hold, release, hold sequence continue smoothly.

The end values a write makes the bridge report are armed here too, so report_filter can tell them, and the bulb's late
reports of the path travelled, from a real change made elsewhere, which forgets the light. With predicted_state on,
report_filter hides those reports from HA, and so from aiohue's models; what the bridge reported is kept here instead,
so the echo a write expects is worked out from what the bridge holds.
"""

import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ...core.runtime import get_runtime

BRIGHTNESS = "brightness"
# How long after a move ends (or a stop) the bridge's report still can't be trusted.
API_SETTLE_SECONDS = 15
# How far a report may be from an armed end value or the path travelled and still be ours (80 % reads 79.84).
REPORT_TOLERANCE = 0.5
# How far the bulb's late report of a halt may be from the predicted one and still be ours (the rig saw 0.9).
HALT_TOLERANCE = 1.5
# The dimmest step a Hue light makes (1/254), in percent.
MIN_BRIGHTNESS_STEP = 0.4


@dataclass(frozen=True, slots=True)
class Transition:
    start: float
    target: float
    duration: float
    started_at: float

    def value(self, now: float) -> float:
        if self.duration <= 0:
            return self.target
        return self.start + (self.target - self.start) * min((now - self.started_at) / self.duration, 1.0)


@dataclass(slots=True)
class Echo:
    """What a write of ours makes the bridge report at its start, each value matched once, by "on" or "brightness"."""

    values: dict[str, float | bool]
    expires_at: float


@dataclass(frozen=True, slots=True)
class Forgotten:
    echo: Echo | None
    transitions: dict[tuple[str, str], Transition]


class TransitionCache:
    """Transitions keyed by (resource_id, attribute); a stop is a transition of zero duration at the halt value.

    Record a transition only once the bridge has accepted it, or later predictions follow one that never ran.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._transitions: dict[tuple[str, str], Transition] = {}
        self._echoes: dict[str, Echo] = {}
        # The bridge's last report of a value HA was not shown, by resource and "on" or "brightness".
        self._hidden: dict[str, dict[str, float | bool]] = {}

    def value(self, resource_id: str, attribute: str, reported: float) -> float:
        """The predicted value inside the guard window, else the reported one."""
        if (transition := self._live(resource_id, attribute)) is None:
            return reported
        return transition.value(self.clock())

    def tracks(self, resource_id: str, attribute: str) -> bool:
        """Whether a move or stop on this resource is still inside its guard window."""
        return self._live(resource_id, attribute) is not None

    def running(self, resource_id: str, attribute: str) -> Transition | None:
        """The move still under way on this resource, if any; a stop or a finished move is not one."""
        if (transition := self._live(resource_id, attribute)) is None:
            return None
        return transition if self.clock() < transition.started_at + transition.duration else None

    def path(self, resource_id: str, attribute: str) -> tuple[float, float] | None:
        """The lowest and highest value the bulb may report inside the guard window: start to target while the move
        runs (a bulb's fade isn't a straight line, and ran 8 % ahead of one on the rig), then start to where it
        ended or halted."""
        if (transition := self._live(resource_id, attribute)) is None:
            return None
        if self.running(resource_id, attribute) is not None:
            return tuple(sorted((transition.start, transition.target)))
        return tuple(sorted((transition.start, transition.value(self.clock()))))

    def on_path(self, resource_id: str, attribute: str, value: float) -> bool:
        """Whether a report is a point the light passes through, so the bulb's own report rather than a change."""
        if (path := self.path(resource_id, attribute)) is None:
            return False
        stopped = self._live(resource_id, attribute).duration == 0
        tolerance = HALT_TOLERANCE if stopped else REPORT_TOLERANCE
        return path[0] - tolerance <= value <= path[1] + tolerance

    def arm(self, resource_id: str, values: dict[str, float | bool], duration: float) -> None:
        """Expect the bridge to report these values once each; arm before the write, which it may echo first."""
        if values:
            self._echoes[resource_id] = Echo(dict(values), self.clock() + duration + API_SETTLE_SECONDS)

    def disarm(self, resource_id: str) -> None:
        """For a write the bridge refused, so it never reports the values armed for it."""
        self._echoes.pop(resource_id, None)

    async def write_armed(self, echoes: dict[str, dict[str, float | bool]], duration: float, write: Awaitable) -> None:
        """Arm each light's echo, then write: the bridge may report before the write returns. A refusal disarms."""
        for resource_id, values in echoes.items():
            self.arm(resource_id, values, duration)
        try:
            await write
        except Exception:
            for resource_id in echoes:
                self.disarm(resource_id)
            raise

    def echoed(self, resource_id: str, key: str, value: float | bool) -> bool:
        """Whether the value is one armed under key, which it then consumes: the bridge reports each end value once."""
        if (echo := self._echoes.get(resource_id)) is None or key not in echo.values:
            return False
        if self.clock() > echo.expires_at:
            del self._echoes[resource_id]
            return False
        armed = echo.values[key]
        if isinstance(armed, bool) or isinstance(value, bool):
            matched = armed is value
        else:
            matched = abs(armed - value) <= REPORT_TOLERANCE
        if matched:
            del echo.values[key]
        return matched

    def hidden(self, resource_id: str, values: dict[str, float | bool]) -> None:
        """The bridge reported these values and HA (so aiohue) was not shown them."""
        self._hidden.setdefault(resource_id, {}).update(values)

    def shown(self, resource_id: str, keys: Iterable[str]) -> None:
        """A report of these keys reached aiohue, which holds the bridge's values for them again."""
        if (hidden := self._hidden.get(resource_id)) is not None:
            for key in keys:
                hidden.pop(key, None)

    def release(self, resource_id: str) -> dict[str, float | bool]:
        """The bridge's values aiohue was not shown, now to be shown, so no longer kept here."""
        return self._hidden.pop(resource_id, {})

    def bridge_value(self, resource_id: str, key: str, held: float | bool) -> float | bool:
        """What the bridge last reported for key: aiohue's value (held), unless it was hidden from aiohue since."""
        return self._hidden.get(resource_id, {}).get(key, held)

    def follows(self, resource_id: str) -> bool:
        """Whether a write of ours is still expected to report, or a transition is inside its guard window."""
        if (echo := self._echoes.get(resource_id)) is not None and echo.values and self.clock() <= echo.expires_at:
            return True
        return any(self._live(rid, attribute) for rid, attribute in list(self._transitions) if rid == resource_id)

    def forget(self, resource_id: str) -> Forgotten:
        """A real change made elsewhere: drop every prediction and armed echo for the resource, returned for restore."""
        transitions = {
            key: self._transitions.pop(key) for key in [key for key in self._transitions if key[0] == resource_id]
        }
        return Forgotten(self._echoes.pop(resource_id, None), transitions)

    def restore(self, resource_id: str, forgotten: Forgotten) -> None:
        """Put back what forget dropped, for a write the bridge refused."""
        if forgotten.echo is not None:
            self._echoes[resource_id] = forgotten.echo
        self._transitions.update(forgotten.transitions)

    def _live(self, resource_id: str, attribute: str) -> Transition | None:
        """The entry inside its guard window, pruning it once expired."""
        key = (resource_id, attribute)
        if (transition := self._transitions.get(key)) is None:
            return None
        if self.clock() - transition.started_at > transition.duration + API_SETTLE_SECONDS:
            del self._transitions[key]
            return None
        return transition

    def moving(
        self,
        resource_id: str,
        attribute: str,
        start: float,
        target: float,
        duration: float,
        started_at: float | None = None,
    ) -> None:
        """started_at: when the write was sent, as the bridge starts the fade once it has it; else now."""
        started_at = self.clock() if started_at is None else started_at
        self._transitions[(resource_id, attribute)] = Transition(start, target, duration, started_at)

    def stopped(self, resource_id: str, attribute: str, value: float) -> None:
        self.moving(resource_id, attribute, value, value, 0.0)


def transition_cache(hass: HomeAssistant) -> TransitionCache:
    state = get_runtime(hass).integration_state
    if (cache := state.get("hue")) is None:
        cache = state["hue"] = TransitionCache()
    return cache
