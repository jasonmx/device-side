from dataclasses import dataclass, field
from typing import ClassVar

import probatio
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN
from ..core.feature import Feature
from ..core.models import LIGHT_FIELD_SCHEMA, FeatureKind, LightFields, TimedRequest


@dataclass(frozen=True, slots=True)
class TurnOnForRequest(TimedRequest):
    light: LightFields = field(default_factory=LightFields)

    def fields_present(self) -> frozenset[str]:
        return self.light.present()


def parse_duration(call: ServiceCall) -> float:
    seconds = call.data["duration"].total_seconds()
    if seconds <= 0:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_duration")
    return seconds


class TurnOnFor(Feature[TurnOnForRequest]):
    """Turn on now; the device turns itself off after the duration."""

    key: ClassVar[str] = "turn_on_for"
    kind: ClassVar[FeatureKind] = FeatureKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light", "switch"})
    fields: ClassVar[dict] = {probatio.Required("duration"): cv.positive_time_period, **LIGHT_FIELD_SCHEMA}

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> TurnOnForRequest:
        return TurnOnForRequest(duration_s=parse_duration(call), light=LightFields.from_data(call.data))


FEATURE = TurnOnFor
