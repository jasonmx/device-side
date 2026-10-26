"""What a Hue light or room is doing mid-move, which the bridge doesn't report.

While a transition runs the bridge (and so HA) reports the end value at once, and after a stop mid-flight it reports
where the light halted late or not at all. Each move and stop is recorded here so the next move, stop or read starts
from the value the light is really at, which is what makes a hold, release, hold sequence continue smoothly.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ...core.runtime import get_runtime

# How long after a move ends (or a stop) the bridge's report still can't be trusted.
API_SETTLE_SECONDS = 15


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


class TransitionCache:
    """Transitions keyed by (resource_id, attribute); a stop is a transition of zero duration at the halt value.

    Record a transition only once the bridge has accepted it, or later predictions follow one that never ran.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._transitions: dict[tuple[str, str], Transition] = {}

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

    def _live(self, resource_id: str, attribute: str) -> Transition | None:
        """The entry inside its guard window, pruning it once expired."""
        key = (resource_id, attribute)
        if (transition := self._transitions.get(key)) is None:
            return None
        if self.clock() - transition.started_at > transition.duration + API_SETTLE_SECONDS:
            del self._transitions[key]
            return None
        return transition

    def moving(self, resource_id: str, attribute: str, start: float, target: float, duration: float) -> None:
        self._transitions[(resource_id, attribute)] = Transition(start, target, duration, self.clock())

    def stopped(self, resource_id: str, attribute: str, value: float) -> None:
        self.moving(resource_id, attribute, value, value, 0.0)


def transition_cache(hass: HomeAssistant) -> TransitionCache:
    state = get_runtime(hass).integration_state
    if (cache := state.get("hue")) is None:
        cache = state["hue"] = TransitionCache()
    return cache
