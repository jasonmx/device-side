"""Fabricate Zigbee2MQTT entities the way Z2M registers them via MQTT discovery."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

IEEE = "0x00124b0012345678"


def z2m_entry(hass: HomeAssistant) -> MockConfigEntry:
    """One loaded MQTT config entry for Z2M (all Z2M devices share a single entry)."""
    entry = MockConfigEntry(domain="mqtt")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def add_z2m_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    ieee: str = IEEE,
    state: str = "off",
    attributes: dict | None = None,
) -> str:
    """Register one Z2M device entity with the identifier Z2M writes via MQTT discovery.

    Each device has its own device-registry entry (keyed by ieee); all share one config entry.
    """
    domain, object_id = entity_id.split(".")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("mqtt", f"zigbee2mqtt_{ieee}")},
    )
    er.async_get(hass).async_get_or_create(
        domain,
        "mqtt",
        ieee,
        suggested_object_id=object_id,
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(entity_id, state, attributes or {})
    return entity_id
