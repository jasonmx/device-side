"""Detect Zigbee2MQTT entities by the device identifier Z2M registers via MQTT discovery."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

_Z2M_IDENTIFIER_PREFIX = "zigbee2mqtt_"


def detect(hass: HomeAssistant, entry: er.RegistryEntry, device: dr.DeviceEntry | None) -> bool:
    """True when this MQTT entity's device carries a Zigbee2MQTT identifier.

    Z2M registers each device with identifier ("mqtt", "zigbee2mqtt_<ieee>") via MQTT discovery;
    this prefix distinguishes Z2M devices from other mqtt-platform entities.
    """
    if device is None:
        return False
    return any(itype == "mqtt" and ident.startswith(_Z2M_IDENTIFIER_PREFIX) for itype, ident in device.identifiers)
