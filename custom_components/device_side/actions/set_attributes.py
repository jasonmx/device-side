from dataclasses import dataclass, field
from typing import ClassVar

import probatio
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..core.action import Action
from ..core.models import LIGHT_FIELD_SCHEMA, ActionKind, LightFields, Request

# Percent, as on Hue: the 0.4 % floor is the dimmest step a Hue light makes (1/254).
_PERCENT = probatio.All(probatio.Coerce(float), probatio.Range(min=0.4, max=100))
LIMITS = ("min_brightness", "max_brightness")


@dataclass(frozen=True, slots=True)
class SetAttributesRequest(Request):
    light: LightFields = field(default_factory=LightFields)
    min_brightness: float | None = None
    max_brightness: float | None = None

    def fields_present(self) -> frozenset[str]:
        return self.light.present() | {name for name in LIMITS if getattr(self, name) is not None}


class SetAttributes(Action[SetAttributesRequest]):
    """Write brightness, color temperature or color to the device without changing whether it is on.

    min_brightness and max_brightness clamp the brightness the device already has; an explicit brightness wins.
    """

    key: ClassVar[str] = "set_attributes"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light"})
    fields: ClassVar[dict] = {
        **{marker: validator for marker, validator in LIGHT_FIELD_SCHEMA.items() if marker.schema != "transition"},
        **{probatio.Optional(name): _PERCENT for name in LIMITS},
    }

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> SetAttributesRequest:
        request = SetAttributesRequest(
            light=LightFields.from_data(call.data), **{name: call.data.get(name) for name in LIMITS}
        )
        if not request.fields_present():
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_set")
        return request


ACTION = SetAttributes
