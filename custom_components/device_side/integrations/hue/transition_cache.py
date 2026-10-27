"""What a Hue light or room is doing mid-move, which the bridge doesn't report.

While a transition runs the bridge (and so HA) reports the end value at once, and after a stop mid-flight it reports
where the light halted late or not at all. Each move and stop is recorded here so the next move, stop or read starts
from the value the light is really at, which is what makes a hold, release, hold sequence continue smoothly.

A transition is recorded just before its write, as the bridge may report before the write returns, and while it is live
report_filter takes the light's reports of its attribute as ours. With predicted_state on, report_filter hides those
reports from HA, and so from aiohue's models; what the bridge reported is kept here instead, to hand back to HA once
nothing predicts the light.
"""

import time
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ...core.runtime import get_runtime

BRIGHTNESS = "brightness"
# How long after a move ends (or a stop) the bridge's report still can't be trusted.
API_SETTLE_SECONDS = 15
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


class TransitionCache:
    """Transitions keyed by (resource_id, attribute); a stop is a transition of zero duration at the halt value.

    Record a transition inside recording(), so a write the bridge refuses leaves the prediction it had.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._transitions: dict[tuple[str, str], Transition] = {}
        # The bridge's last report of a value HA was not shown, by resource and report key (attributes.REPORT_KEYS).
        self._hidden: dict[str, dict[str, float | bool]] = {}

    def value(self, resource_id: str, attribute: str, reported: float) -> float:
        """The predicted value inside the guard window, else the reported one."""
        if (transition := self.live(resource_id, attribute)) is None:
            return reported
        return transition.value(self.clock())

    def tracks(self, resource_id: str, attribute: str) -> bool:
        """Whether a move or stop on this resource is still inside its guard window."""
        return self.live(resource_id, attribute) is not None

    def running(self, resource_id: str, attribute: str) -> Transition | None:
        """The move still under way on this resource, if any; a stop or a finished move is not one."""
        if (transition := self.live(resource_id, attribute)) is None:
            return None
        return transition if self.clock() < transition.started_at + transition.duration else None

    def halted(self, resource_id: str, attribute: str) -> bool:
        """Whether a stop on this resource is still inside its guard window."""
        return (transition := self.live(resource_id, attribute)) is not None and transition.duration == 0

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

    def attributes(self, resource_id: str) -> list[str]:
        """The attributes of the resource a move or stop is still inside its guard window for."""
        keys = [key for key in self._transitions if key[0] == resource_id]
        return [attribute for rid, attribute in keys if self.live(rid, attribute)]

    def follows(self, resource_id: str) -> bool:
        """Whether a move or stop on the resource is still inside its guard window."""
        return bool(self.attributes(resource_id))

    def forget(self, resource_id: str) -> dict[tuple[str, str], Transition]:
        """A real change made elsewhere: drop every prediction for the resource, returned for restore."""
        return {key: self._transitions.pop(key) for key in [key for key in self._transitions if key[0] == resource_id]}

    def restore(self, transitions: dict[tuple[str, str], Transition]) -> None:
        """Put back what forget dropped, for a write the bridge refused."""
        self._transitions.update(transitions)

    @asynccontextmanager
    async def recording(self, keys: Iterable[tuple[str, str]]) -> AsyncIterator[None]:
        """Around a write and the transitions it makes, recorded first: the bridge may report before the write returns.
        A refusal puts back what each (resource_id, attribute) held before."""
        before = {key: self._transitions.get(key) for key in keys}
        try:
            yield
        except Exception:
            for key, transition in before.items():
                if transition is None:
                    self._transitions.pop(key, None)
                else:
                    self._transitions[key] = transition
            raise

    def live(self, resource_id: str, attribute: str) -> Transition | None:
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
    ) -> None:
        """Record before the write is sent, as the bridge starts the fade once it has it."""
        self._transitions[(resource_id, attribute)] = Transition(start, target, duration, self.clock())

    def stopped(self, resource_id: str, attribute: str, value: float) -> None:
        self.moving(resource_id, attribute, value, value, 0.0)


def transition_cache(hass: HomeAssistant) -> TransitionCache:
    state = get_runtime(hass).integration_state
    if (cache := state.get("hue")) is None:
        cache = state["hue"] = TransitionCache()
    return cache
