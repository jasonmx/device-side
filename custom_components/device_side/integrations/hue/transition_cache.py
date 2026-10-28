"""Hue's transition cache: the core one with the bridge's settle window, and the reports kept from HA.

While a transition is live report_filter takes the light's reports of its attribute as ours. With predicted_state on,
report_filter hides those reports from HA, and so from aiohue's models; what the bridge reported is kept here instead,
to hand back to HA once nothing predicts the light.
"""

import time
from collections.abc import Callable, Iterable

from homeassistant.core import HomeAssistant

from ...core import transition

# How long after a move ends (or a stop) the bridge's report still can't be trusted.
API_SETTLE_SECONDS = 15
# The dimmest step a Hue light makes (1/254), in percent.
MIN_BRIGHTNESS_STEP = 0.4
# The smallest color temperature step the bridge takes, in mirek.
MIN_MIREK_STEP = 1


class HueTransitionCache(transition.TransitionCache):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(API_SETTLE_SECONDS, clock)
        # The bridge's last report of a value HA was not shown, by resource and report key (attributes.REPORT_KEYS).
        self._hidden: dict[str, dict[str, float | bool]] = {}

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


def transition_cache(hass: HomeAssistant) -> HueTransitionCache:
    return transition.transition_cache(hass, "hue", HueTransitionCache)
