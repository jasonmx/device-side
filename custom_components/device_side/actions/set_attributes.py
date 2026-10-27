from dataclasses import dataclass, field, replace
from typing import ClassVar, Self

import probatio
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..core.action import Action
from ..core.models import LIGHT_FIELD_SCHEMA, ActionKind, LightFields, Request

# Percent, as on Hue and hue_dimmer, whose calls these must accept unchanged. A brightness of 0 goes to the bridge,
# which sets the light's lowest level, as hue_dimmer's calls did; the UI selector starts at 0.4.
_PERCENT = probatio.All(probatio.Coerce(float), probatio.Range(min=0, max=100))
_COLORS = ("color_temp_kelvin", "hs_color", "rgb_color", "xy_color")
LIMITS = ("min_brightness", "max_brightness")
# 0 leaves these unset, as on hue_dimmer, so a template can pass 0 for "no limit".
_UNSET_AT_ZERO = (*LIMITS, "color_temp_kelvin")


@dataclass(frozen=True, slots=True)
class SetAttributesRequest(Request):
    light: LightFields = field(default_factory=LightFields)  # colors only: brightness here is percent, not 0-255
    brightness: float | None = None
    min_brightness: float | None = None
    max_brightness: float | None = None

    def fields_present(self) -> frozenset[str]:
        own = {name for name in ("brightness", *LIMITS) if getattr(self, name) is not None}
        return self.light.present() | own

    def without(self, names: frozenset[str]) -> Self:
        own = {name: None for name in ("brightness", *LIMITS) if name in names}
        return replace(self, light=self.light.without(names), **own)

    def nothing_to_do(self) -> bool:
        return not self.fields_present()


class SetAttributes(Action[SetAttributesRequest]):
    """Write brightness, color temperature or color to the device without changing whether it is on.

    min_brightness and max_brightness clamp the brightness the device already has; an explicit brightness wins.
    """

    key: ClassVar[str] = "set_attributes"
    kind: ClassVar[ActionKind] = ActionKind.COMMAND
    domains: ClassVar[frozenset[str]] = frozenset({"light"})
    fields: ClassVar[dict] = {
        **{probatio.Optional(name): _PERCENT for name in ("brightness", *LIMITS)},
        # light.turn_on's validators without its one-color rule: given several colors, rgb_color wins, then
        # hs_color, then xy_color, as on hue_dimmer.
        **{
            probatio.Optional(marker.schema): validator
            for marker, validator in LIGHT_FIELD_SCHEMA.items()
            if marker.schema in _COLORS
        },
    }

    @classmethod
    def parse(cls, hass: HomeAssistant, call: ServiceCall) -> SetAttributesRequest:
        data = {name: value for name, value in call.data.items() if not (name in _UNSET_AT_ZERO and value == 0)}
        request = SetAttributesRequest(
            light=LightFields.from_data({name: value for name, value in data.items() if name in _COLORS}),
            **{name: data.get(name) for name in ("brightness", *LIMITS)},
        )
        if not request.fields_present():
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="nothing_to_set")
        return request


ACTION = SetAttributes
