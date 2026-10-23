"""Platform "fake_special": claims "fake" entities whose device is special (like Z2M on mqtt); no group hook."""

from custom_components.device_side.core.capabilities import CellCapabilities, PlatformInfo

from ..fake_platform import LIMITS, is_group
from ..scripted import ScriptedCell


def detect(hass, entry, device) -> bool:
    return device is not None and any(ident[1].startswith("special") for ident in device.identifiers)


PLATFORM = PlatformInfo(
    key="fake_special", title="Fake special", ha_integration="fake", detect=detect, is_group=is_group
)


class SpecialTurnOnFor(ScriptedCell):
    feature = "turn_on_for"
    platform = "fake_special"
    capabilities = CellCapabilities(domains=frozenset({"light", "switch"}), duration=LIMITS)


CELLS = [SpecialTurnOnFor]
