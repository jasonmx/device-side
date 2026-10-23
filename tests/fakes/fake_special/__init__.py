"""Platform "fake_special": claims "fake" entities whose device is special (like Z2M on mqtt); no group hook."""

from custom_components.device_side.core.capabilities import AdapterCapabilities, PlatformInfo

from ..fake_platform import LIMITS, is_group
from ..scripted import ScriptedAdapter


def detect(hass, entry, device) -> bool:
    return device is not None and any(ident[1].startswith("special") for ident in device.identifiers)


PLATFORM = PlatformInfo(
    key="fake_special", title="Fake special", ha_integration="fake", detect=detect, is_group=is_group
)


class SpecialTurnOnFor(ScriptedAdapter):
    feature = "turn_on_for"
    platform = "fake_special"
    capabilities = AdapterCapabilities(domains=frozenset({"light", "switch"}), duration=LIMITS)


ADAPTERS = [SpecialTurnOnFor]
