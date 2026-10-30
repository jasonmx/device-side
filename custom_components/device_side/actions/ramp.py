"""What the raise and lower actions share: one request, its fields and its parse. Each action is one attribute moved
one way; stop halts them all."""

from dataclasses import dataclass, replace
from typing import Any, ClassVar, Self

import probatio
from homeassistant.core import HomeAssistant, ServiceCall

from ..core.action import Action
from ..core.models import ActionKind, Request
from ..core.transition import BRIGHTNESS, SATURATION

HUE = "hue"
__all__ = ["BRIGHTNESS", "HUE", "SATURATION", "Ramp", "RampRequest", "limit_field"]

DEFAULT_SWEEP_TIME = 5.0


def limit_field(low: float, high: float) -> dict[probatio.Marker, Any]:
    """The optional limit, a percentage from low to high: where the move ends instead of the range end."""
    return {probatio.Optional("limit"): probatio.All(probatio.Coerce(float), probatio.Range(min=low, max=high))}


@dataclass(frozen=True, slots=True)
class RampRequest(Request):
    """One attribute moving one way, sweep_time per full range. A target that lacks the attribute drops it, which
    leaves the request nothing to do."""

    attribute: str
    up: bool
    sweep_time: float = DEFAULT_SWEEP_TIME
    limit: float | None = None
    dropped: bool = False

    def fields_present(self) -> frozenset[str]:
        return frozenset() if self.dropped else frozenset({self.attribute})

    def without(self, names: frozenset[str]) -> Self:
        return replace(self, dropped=True) if self.attribute in names else self

    def nothing_to_do(self) -> bool:
        return self.dropped

    def end(self) -> float:
        """The value the move stops at: its limit, or the range end."""
        return self.limit if self.limit is not None else (100.0 if self.up else 0.0)


class Ramp(Action[RampRequest]):
    """Start one attribute moving one way at a steady speed until it reaches its range end or limit; stop halts it.

    sweep_time is how long a full range takes, so the speed is the same wherever the move starts.
    """

    attribute: ClassVar[str]
    up: ClassVar[bool]
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light"})
    fields: ClassVar[dict] = {
        probatio.Optional("sweep_time", default=DEFAULT_SWEEP_TIME): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0.1)
        ),
    }

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> RampRequest:
        return RampRequest(cls.attribute, cls.up, call.data["sweep_time"], call.data.get("limit"))
