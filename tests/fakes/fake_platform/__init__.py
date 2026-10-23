"""Platform "fake": a generic platform with native groups whose members it can list."""

from custom_components.device_side.core.capabilities import AdapterCapabilities, DurationLimits, PlatformInfo
from custom_components.device_side.core.resolver import resolve

from ..scripted import ScriptedAdapter

LIMITS = DurationLimits(min_s=1, max_s=100, resolution_s=0.1)


def is_group(hass, target) -> bool:
    return target.entry.unique_id.startswith("group:")


def expand_group(hass, target):
    registry = hass.data["device_side"].registry
    members = target.state.attributes.get("fake_members", []) if target.state else []
    return [t for m in members if not isinstance(t := resolve(hass, registry, m, target.entity_id), str)]


PLATFORM = PlatformInfo(
    key="fake",
    title="Fake",
    ha_integration="fake",
    is_group=is_group,
    expand_group=expand_group,
    max_concurrency=2,
)


class FakeTurnOnFor(ScriptedAdapter):
    feature = "turn_on_for"
    platform = "fake"
    capabilities = AdapterCapabilities(
        domains=frozenset({"light", "switch"}),
        duration=LIMITS,
        supports_fields=frozenset({"brightness", "transition"}),
    )


class FakeTurnOffFor(ScriptedAdapter):
    feature = "turn_off_for"
    platform = "fake"
    capabilities = AdapterCapabilities(domains=frozenset({"switch"}), duration=LIMITS, native_groups=True)


ADAPTERS = [FakeTurnOnFor, FakeTurnOffFor]
