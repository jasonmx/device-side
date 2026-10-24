from typing import ClassVar

import probatio
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .turn_on_for import parse_duration
from ..core.action import Action
from ..core.models import ActionKind, TimedRequest


class TurnOffFor(Action[TimedRequest]):
    """Turn off now; the device turns itself back on after the duration."""

    key: ClassVar[str] = "turn_off_for"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light", "switch"})
    fields: ClassVar[dict] = {probatio.Required("duration"): cv.positive_time_period}

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> TimedRequest:
        return TimedRequest(duration_s=parse_duration(call))


ACTION = TurnOffFor
