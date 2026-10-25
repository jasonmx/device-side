"""Extract the Z2M device address from the HA device registry."""

from homeassistant.helpers import device_registry as dr

from ...core.models import Target

_Z2M_PREFIX = "zigbee2mqtt_"
_Z2M_BASE_TOPIC = "zigbee2mqtt"


def z2m_address(device: dr.DeviceEntry) -> str | None:
    """The Z2M address (IEEE or group id) from the device identifier, or None.

    Z2M registers devices with identifier ("mqtt", "zigbee2mqtt_<address>"). The address is
    the IEEE for individual devices; for Z2M groups it follows whatever Z2M assigned.
    """
    for itype, ident in device.identifiers:
        if itype == "mqtt" and ident.startswith(_Z2M_PREFIX):
            return ident[len(_Z2M_PREFIX):]
    return None


def command_topic(target: Target) -> str | None:
    """MQTT command topic for this Z2M entity, or None when the address cannot be determined.

    Assumes the default Z2M base topic ("zigbee2mqtt"). A custom base topic is a known sharp edge
    documented in docs/integrations.md; see also the rig verification list.
    """
    if target.device is None:
        return None
    addr = z2m_address(target.device)
    if addr is None:
        return None
    return f"{_Z2M_BASE_TOPIC}/{addr}/set"
