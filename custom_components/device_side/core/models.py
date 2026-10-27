from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any

import probatio
from homeassistant.components.light.const import LIGHT_TURN_ON_SCHEMA
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ..const import LIGHT_FIELDS


class Status(StrEnum):
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"
    SENT = "sent"
    CONFIRMED = "confirmed"
    UNCHANGED = "unchanged"  # nothing sent: the target is already where the call would leave it; detail says why


# Statuses that mean the command did not reach the device; a call where every target ends in one of these raises.
FAILED = frozenset({Status.UNSUPPORTED, Status.REJECTED})


class ActionKind(StrEnum):
    COMMAND = "command"
    SETTING = "setting"
    QUERY = "query"


# light.turn_on's own validators for the fields we accept, so ranges and the one-color-at-a-time rule never drift
# from core. Plain-string keys (transition) become Optional markers so every field is a Marker.
LIGHT_FIELD_SCHEMA: dict[probatio.Marker, Any] = {
    (key if isinstance(key, probatio.Marker) else probatio.Optional(key)): validator
    for key, validator in LIGHT_TURN_ON_SCHEMA.items()
    if str(key) in LIGHT_FIELDS
}


@dataclass(frozen=True, slots=True)
class LightFields:
    brightness: int | None = None
    color_temp_kelvin: int | None = None
    hs_color: tuple[float, float] | None = None
    rgb_color: tuple[int, int, int] | None = None
    xy_color: tuple[float, float] | None = None
    transition: float | None = None

    @classmethod
    def from_data(cls, data: dict) -> LightFields:
        return cls(**{name: data[name] for name in LIGHT_FIELDS if name in data})

    def present(self) -> frozenset[str]:
        return frozenset(field.name for field in fields(self) if getattr(self, field.name) is not None)

    def as_turn_on_data(self) -> dict:
        return {name: getattr(self, name) for name in sorted(self.present())}


@dataclass(frozen=True, slots=True)
class Request:
    """Base for an action's parsed call. Subclasses add their fields."""

    # The caller's context, set by the dispatcher: adapters forward it so an admin-only service checks the caller.
    context: Context | None = field(default=None, kw_only=True)

    def fields_present(self) -> frozenset[str]:
        """light.turn_on fields this request carries; adapters must have them in scope.fields."""
        return frozenset()


@dataclass(frozen=True, slots=True)
class TimedRequest(Request):
    """A request with a duration the dispatcher clamps to each adapter's DurationLimits."""

    duration_s: float


@dataclass(frozen=True, slots=True)
class Target:
    entity_id: str
    domain: str
    integration: str
    entry: er.RegistryEntry
    device: dr.DeviceEntry | None
    config_entry: ConfigEntry
    state: State | None
    via_group: str | None = None
    # The switch_as_x light the caller named; the adapter sees the wrapped switch, results report the light.
    via_wrapper: str | None = None
    is_group: bool = False

    @property
    def reported_id(self) -> str:
        """The entity_id results are keyed on: the one the caller targeted."""
        return self.via_wrapper or self.entity_id


@dataclass(slots=True)
class EntityResult:
    entity_id: str
    status: Status
    integration: str | None = None
    clamped_to: float | None = None
    detail: str | None = None
    data: dict | None = None

    def as_response(self) -> dict:
        response: dict[str, Any] = {"status": self.status.value}
        for name in ("integration", "clamped_to", "detail"):
            if (value := getattr(self, name)) is not None:
                response[name] = value
        if self.data is not None:
            response["attributes"] = self.data
        return response
