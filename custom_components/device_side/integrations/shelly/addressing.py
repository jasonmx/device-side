"""Which RPC component instance a Shelly entity drives, and the device that serves it.

Read from the registry and the Shelly config entry only, never from aioshelly: importing it (or
homeassistant.components.shelly, which does) would make this adapter module unavailable wherever Shelly isn't installed.
"""

import re
from dataclasses import dataclass
from typing import Any

from ...core.models import Target

# Relays and lights carry unique_id "{mac}-{key}" (shelly/switch.py RpcRelaySwitch, shelly/light.py
# RpcShellyLightBase). Every other Shelly switch (virtual booleans, scripts, circuit breakers) has another suffix
# or key, and has no flip-back timer.
_UNIQUE_ID = re.compile(r"^[^-]+-(?P<key>switch|light|cct|rgb|rgbcct|rgbw):(?P<id>\d+)$")

COMPONENTS = {"switch": "Switch", "light": "Light", "cct": "CCT", "rgb": "RGB", "rgbcct": "RGBCCT", "rgbw": "RGBW"}

_DIMMABLE = frozenset({"brightness", "transition"})

# light.turn_on fields each component takes, as shelly/light.py translates them. A Switch shown as a light is on/off.
COMPONENT_FIELDS = {
    "Switch": frozenset(),
    "Light": _DIMMABLE,
    "CCT": _DIMMABLE | {"color_temp_kelvin"},
    "RGB": _DIMMABLE | {"rgb_color"},
    "RGBW": _DIMMABLE | {"rgb_color"},
    "RGBCCT": _DIMMABLE | {"color_temp_kelvin", "rgb_color"},
}


@dataclass(frozen=True, slots=True)
class RpcAddress:
    component: str
    id: int


def rpc_device(target: Target) -> Any | None:
    """The aioshelly RpcDevice behind the entity, or None on a Gen1 (block) device."""
    coordinator = getattr(getattr(target.config_entry, "runtime_data", None), "rpc", None)
    return coordinator.device if coordinator is not None else None


def address(target: Target) -> RpcAddress | None:
    if not (match := _UNIQUE_ID.match(target.entry.unique_id)):
        return None
    return RpcAddress(COMPONENTS[match["key"]], int(match["id"]))


def unsupported_reason(
    target: Target, fields: frozenset[str] = frozenset(), capabilities: frozenset[str] | None = None
) -> str | None:
    """Why this entity can't take a timed Set with these light fields within the capabilities in scope, or None."""
    if rpc_device(target) is None:
        return "gen1_unsupported"
    if (rpc := address(target)) is None:
        return "not_addressable"
    if capabilities is not None and rpc.component not in capabilities:
        return "capability_not_tested"
    if target.domain == "light" and fields - COMPONENT_FIELDS[rpc.component]:
        return "fields_not_supported"
    return None
