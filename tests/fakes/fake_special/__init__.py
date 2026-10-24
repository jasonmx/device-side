"""Integration "fake_special": takes "fake" entities whose device is special (like Z2M on mqtt); no group hook."""

from custom_components.device_side.core.scope import AdapterScope, IntegrationInfo

from ..fake_integration import LIMITS, is_group
from ..scripted import ScriptedAdapter


def detect(hass, entry, device) -> bool:
    return device is not None and any(ident[1].startswith("special") for ident in device.identifiers)


INTEGRATION = IntegrationInfo(
    key="fake_special", title="Fake special", ha_domain="fake", detect=detect, is_group=is_group
)


class SpecialTurnOnFor(ScriptedAdapter):
    action = "turn_on_for"
    integration = "fake_special"
    scope = AdapterScope(domains=frozenset({"light", "switch"}), duration=LIMITS)


ADAPTERS = [SpecialTurnOnFor]
