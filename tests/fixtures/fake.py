"""Fabricate entities on the fake platforms and HA groups over them."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


def fake_config_entry(hass: HomeAssistant, state: ConfigEntryState = ConfigEntryState.LOADED) -> MockConfigEntry:
    entry = MockConfigEntry(domain="fake")
    entry.add_to_hass(hass)
    entry.mock_state(hass, state)
    return entry


def add_fake_entity(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_id: str,
    state: str = "off",
    attributes: dict | None = None,
    unique_id: str | None = None,
    identifier: str | None = None,
) -> str:
    domain, object_id = entity_id.split(".")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={("fake", identifier or object_id)}
    )
    er.async_get(hass).async_get_or_create(
        domain,
        "fake",
        unique_id or object_id,
        suggested_object_id=object_id,
        config_entry=config_entry,
        device_id=device.id,
    )
    hass.states.async_set(entity_id, state, attributes or {})
    return entity_id


def add_fake_native_group(hass, config_entry, entity_id: str, members: list[str]) -> str:
    return add_fake_entity(
        hass, config_entry, entity_id, attributes={"fake_members": members}, unique_id=f"group:{entity_id}"
    )


def add_ha_group(hass: HomeAssistant, entity_id: str, members: list[str]) -> str:
    """A group helper entity (light group, switch group); legacy group.* ids are state-only, as in core."""
    domain, object_id = entity_id.split(".")
    if domain != "group":
        er.async_get(hass).async_get_or_create(domain, "group", object_id, suggested_object_id=object_id)
    hass.states.async_set(entity_id, "on", {"entity_id": members})
    return entity_id
