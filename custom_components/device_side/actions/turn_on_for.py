from dataclasses import dataclass, field, replace
from typing import ClassVar, Self

import probatio
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN
from ..core.action import Action
from ..core.models import LIGHT_FIELD_SCHEMA, ActionKind, LightFields, TimedRequest


@dataclass(frozen=True, slots=True)
class TurnOnForRequest(TimedRequest):
    light: LightFields = field(default_factory=LightFields)

    def fields_present(self) -> frozenset[str]:
        return self.light.present()

    def without(self, names: frozenset[str]) -> Self:
        # Never nothing to do: with every field dropped the timer still runs, as light.turn_on still turns on.
        return replace(self, light=self.light.without(names))


# 10 ms steps; the dispatcher applies the 50 ms floor (core/duration.py) so it can report clamped_to.
RESOLUTION_DIGITS = 2


def parse_duration(call: ServiceCall) -> float:
    seconds = call.data["duration"].total_seconds()
    if seconds <= 0:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_duration")
    return round(seconds, RESOLUTION_DIGITS)


class TurnOnFor(Action[TurnOnForRequest]):
    """Turn on now; the device turns itself off after the duration."""

    key: ClassVar[str] = "turn_on_for"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light", "switch"})
    fields: ClassVar[dict] = {probatio.Required("duration"): cv.positive_time_period, **LIGHT_FIELD_SCHEMA}

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> TurnOnForRequest:
        return TurnOnForRequest(duration_s=parse_duration(call), light=LightFields.from_data(call.data))


ACTION = TurnOnFor
