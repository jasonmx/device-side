"""What each attribute a move fades means in the bridge's reports.

A report key names one value in a light's or grouped_light's event ("on", "brightness"). A write of an attribute makes
the bridge report the keys that attribute owns, and only those: a brightness move reports on and brightness, never a
color temperature, and a color temperature move only mirek (Tested behavior in docs/integrations.md).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .transition_cache import BRIGHTNESS, COLOR_TEMP

# Where each report key sits in an event, as (object, field): every key an attribute owns or could own.
REPORT_KEYS: dict[str, tuple[str, str]] = {
    "on": ("on", "on"),
    BRIGHTNESS: ("dimming", "brightness"),
    "mirek": ("color_temperature", "mirek"),
    "xy": ("color", "xy"),
}


@dataclass(frozen=True, slots=True)
class Attribute:
    keys: frozenset[str]  # the report keys a write of it makes the bridge report
    # The report keys' values that show a value of it, with predicted_state on; None for one HA is shown the bridge's
    # reports of, which are only told apart from a change made elsewhere.
    shows: Callable[[float], dict[str, float | bool]] | None


def _brightness(value: float) -> dict[str, float | bool]:
    """0 is off, leaving the stored brightness alone, as a soft off does on the bridge."""
    return {"on": True, BRIGHTNESS: value} if value > 0 else {"on": False}


ATTRIBUTES: dict[str, Attribute] = {
    BRIGHTNESS: Attribute(frozenset({"on", BRIGHTNESS}), _brightness),
    COLOR_TEMP: Attribute(frozenset({"mirek"}), None),
}


def reported_values(event: dict) -> dict[str, float | bool]:
    """The event's values by report key; only what changed is in an event."""
    values: dict[str, float | bool] = {}
    for key, (name, field) in REPORT_KEYS.items():
        if (section := event.get(name)) is not None and field in section:
            values[key] = section[field]
    return values


def event_fields(values: dict[str, float | bool]) -> dict:
    """The event fields that report these values."""
    fields: dict = {}
    for key, value in values.items():
        name, field = REPORT_KEYS[key]
        fields.setdefault(name, {})[field] = value
    return fields


def strip(event: dict, keys: Iterable[str]) -> None:
    """Take these report keys out of the event, and any object left empty."""
    for key in keys:
        name, field = REPORT_KEYS[key]
        if (section := event.get(name)) is not None:
            section.pop(field, None)
            if not section:
                del event[name]
