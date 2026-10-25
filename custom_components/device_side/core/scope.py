from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .models import Target


@dataclass(frozen=True, slots=True)
class DurationLimits:
    min_s: float
    max_s: float


@dataclass(frozen=True, slots=True)
class AdapterScope:
    """The entity domains, capabilities and fields an adapter is known to work with, plus its settings. A capability
    or field nobody has tested is left out of scope and refused, not gated at runtime.
    """

    experimental: bool = False
    domains: frozenset[str] = frozenset({"light"})
    duration: DurationLimits | None = None
    fields: frozenset[str] = frozenset()
    # Device-side capabilities tested on hardware (Shelly: RPC component names); None covers all it can address.
    # A record proves only the capability the call reaches, so a sibling's untested capability is left out here.
    capabilities: frozenset[str] | None = None
    confirmable: bool = False
    native_groups: bool = False
    max_concurrency: int = 4
    notes: tuple[str, ...] = ()


@dataclass(slots=True)
class IntegrationInfo:
    key: str
    title: str
    ha_domain: str
    # Picks this integration over a generic sibling on the same ha_domain (Z2M over plain mqtt).
    detect: Callable[[HomeAssistant, er.RegistryEntry, dr.DeviceEntry | None], bool] | None = None
    # True for an integration-native group (Hue grouped_light, a Z2M or ZHA group entity).
    is_group: Callable[[HomeAssistant, Target], bool] | None = None
    # Members of a native group, for adapters without native_groups; None means membership is unknowable here.
    expand_group: Callable[[HomeAssistant, Target], list[Target]] | None = None
    max_concurrency: int = 4
    available: bool = True
    unavailable_reason: str | None = None
