from dataclasses import dataclass, replace
from typing import ClassVar, Self

import probatio
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..core.action import Action
from ..core.models import ActionKind, Request

UP, DOWN = "up", "down"
WARMER, COOLER = "warmer", "cooler"

# Each attribute's direction words, and its limit field (hue is a cycle, so it has none).
DIRECTIONS = {
    "brightness": (UP, DOWN),
    "color_temp": (WARMER, COOLER),
    "saturation": (UP, DOWN),
    "hue": (UP, DOWN),
}
LIMITS = {"brightness": "brightness_limit", "color_temp": "color_temp_limit", "saturation": "saturation_limit"}

DEFAULT_SWEEP_TIME = 5.0

_PERCENT = probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=100))


@dataclass(frozen=True, slots=True)
class MoveRequest(Request):
    brightness: str | None = None
    color_temp: str | None = None
    saturation: str | None = None
    hue: str | None = None
    sweep_time: float = DEFAULT_SWEEP_TIME
    brightness_limit: float | None = None
    color_temp_limit: int | None = None
    saturation_limit: float | None = None

    def fields_present(self) -> frozenset[str]:
        return frozenset(name for name in (*DIRECTIONS, *LIMITS.values()) if getattr(self, name) is not None)

    def without(self, names: frozenset[str]) -> Self:
        return replace(self, **{name: None for name in names if name in (*DIRECTIONS, *LIMITS.values())})

    def nothing_to_do(self) -> bool:
        return not any(getattr(self, name) for name in DIRECTIONS)


class Move(Action[MoveRequest]):
    """Start moving brightness, color temperature or saturation toward its range end or a limit; stop halts it.

    sweep_time is how long a full-range sweep takes, so the speed is the same wherever the move starts.
    """

    key: ClassVar[str] = "move"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light"})
    fields: ClassVar[dict] = {
        **{probatio.Optional(name): probatio.In(words) for name, words in DIRECTIONS.items()},
        probatio.Optional("sweep_time", default=DEFAULT_SWEEP_TIME): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0.1)
        ),
        probatio.Optional("brightness_limit"): _PERCENT,
        probatio.Optional("color_temp_limit"): probatio.All(probatio.Coerce(int), probatio.Range(min=1000, max=10000)),
        probatio.Optional("saturation_limit"): _PERCENT,
    }

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> MoveRequest:
        names = MoveRequest.__dataclass_fields__
        request = MoveRequest(**{name: value for name, value in call.data.items() if name in names})
        if not any(getattr(request, name) for name in DIRECTIONS):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_move")
        limits = [(name, limit) for name, limit in LIMITS.items() if getattr(request, limit) is not None]
        if orphans := [limit for name, limit in limits if not getattr(request, name)]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="limit_without_direction",
                translation_placeholders={"limits": ", ".join(orphans)},
            )
        return request


ACTION = Move
