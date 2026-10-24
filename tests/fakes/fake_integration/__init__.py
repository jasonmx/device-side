"""Integration "fake": a generic integration with native groups whose members it can list."""

from custom_components.device_side.core.resolver import resolve
from custom_components.device_side.core.scope import AdapterScope, DurationLimits, IntegrationInfo

from ..scripted import ScriptedAdapter

LIMITS = DurationLimits(min_s=1, max_s=100)


def is_group(hass, target) -> bool:
    return target.entry.unique_id.startswith("group:")


def expand_group(hass, target):
    registry = hass.data["device_side"].registry
    members = target.state.attributes.get("fake_members", []) if target.state else []
    return [t for m in members if not isinstance(t := resolve(hass, registry, m, target.entity_id), str)]


INTEGRATION = IntegrationInfo(
    key="fake",
    title="Fake",
    ha_domain="fake",
    is_group=is_group,
    expand_group=expand_group,
    max_concurrency=2,
)


class FakeTurnOnFor(ScriptedAdapter):
    action = "turn_on_for"
    integration = "fake"
    scope = AdapterScope(
        domains=frozenset({"light", "switch"}),
        duration=LIMITS,
        fields=frozenset({"brightness", "transition"}),
    )


class FakeTurnOffFor(ScriptedAdapter):
    action = "turn_off_for"
    integration = "fake"
    scope = AdapterScope(domains=frozenset({"switch"}), duration=LIMITS, native_groups=True)


ADAPTERS = [FakeTurnOnFor, FakeTurnOffFor]
