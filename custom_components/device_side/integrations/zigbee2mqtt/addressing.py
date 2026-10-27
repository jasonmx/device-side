"""Extract the Z2M device or group address from the HA device registry."""

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from ...core.models import Target

_Z2M_PREFIX = "zigbee2mqtt_"
_Z2M_BASE_TOPIC = "zigbee2mqtt"
# Z2M encodes the base topic in a group's identifier as character codes joined with no separator
# (getEncodedBaseTopic in lib/extension/homeassistant.ts).
_ENCODED_BASE_TOPIC = "".join(str(ord(c)) for c in _Z2M_BASE_TOPIC)
# A group's address is <encoded base topic>_<group ID>; a device's is its IEEE, which starts with 0x.
_GROUP_ADDRESS = re.compile(r"^(\d+)_(\d+)$")


def z2m_address(device: dr.DeviceEntry) -> str | None:
    """The address after "zigbee2mqtt_" in the device identifier, or None.

    Z2M registers devices with identifier ("mqtt", "zigbee2mqtt_<ieee>") and groups with
    ("mqtt", "zigbee2mqtt_<encoded base topic>_<group ID>").
    """
    for itype, ident in device.identifiers:
        if itype == "mqtt" and ident.startswith(_Z2M_PREFIX):
            return ident[len(_Z2M_PREFIX):]
    return None


def is_z2m_group(hass: HomeAssistant, target: Target) -> bool:
    """True for a Z2M group entity, whatever its base topic."""
    if target.device is None or (addr := z2m_address(target.device)) is None:
        return False
    return _GROUP_ADDRESS.match(addr) is not None


def topic(target: Target, suffix: str) -> str | None:
    """MQTT topic <base>/<address>/<suffix> for this Z2M entity, or None when it cannot be addressed.

    The suffix is "set" for a command and "get" for a read. A device is addressed by IEEE and a group
    by ID, both under the default base topic. A group's identifier carries its base topic, so a group
    on any other base topic gets None rather than a dead topic; a device's doesn't, so a custom base
    topic still misfires for devices (a sharp edge documented in docs/integrations.md).
    """
    if target.device is None:
        return None
    addr = z2m_address(target.device)
    if addr is None:
        return None
    if group := _GROUP_ADDRESS.match(addr):
        encoded_base, group_id = group.groups()
        if encoded_base != _ENCODED_BASE_TOPIC:
            return None
        return f"{_Z2M_BASE_TOPIC}/{group_id}/{suffix}"
    return f"{_Z2M_BASE_TOPIC}/{addr}/{suffix}"


def state_topic(target: Target) -> str | None:
    """MQTT topic <base>/<friendly name> on which Z2M publishes this entity's state, or None.

    Z2M names the HA device after its friendly name (a user's rename is name_by_user, which this ignores).
    Addressable like topic(), with the same default base topic.
    """
    if topic(target, "set") is None or not target.device.name:
        return None
    return f"{_Z2M_BASE_TOPIC}/{target.device.name}"


def group_id(target: Target) -> str | None:
    """The Z2M group ID of a group entity on the default base topic, or None for anything else."""
    if target.device is None or (addr := z2m_address(target.device)) is None:
        return None
    if (group := _GROUP_ADDRESS.match(addr)) is None or group.group(1) != _ENCODED_BASE_TOPIC:
        return None
    return group.group(2)


def bridge_topic(suffix: str) -> str:
    """Z2M's bridge topic <base>/bridge/<suffix>, under the default base topic like topic()."""
    return f"{_Z2M_BASE_TOPIC}/bridge/{suffix}"
