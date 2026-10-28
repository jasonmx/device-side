"""Fabricate ZHA entities and groups the way the zha library registers them."""

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

IEEE = "00:17:88:01:02:03:04:05"


def zha_entry(hass: HomeAssistant) -> MockConfigEntry:
    """The one loaded ZHA config entry every ZHA device shares."""
    entry = MockConfigEntry(domain="zha")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def add_zha_entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    entity_id: str,
    ieee: str = IEEE,
    unique_id: str | None = None,
    state: str = "off",
    attributes: dict | None = None,
) -> str:
    """Register a ZHA entity; a light's unique_id is "{ieee}-{endpoint_id}" unless one is given."""
    domain, object_id = entity_id.split(".")
    device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("zha", ieee)})
    er.async_get(hass).async_get_or_create(
        domain,
        "zha",
        unique_id or f"{ieee}-11",
        suggested_object_id=object_id,
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(entity_id, state, attributes)
    return entity_id


def zha_group(*members: tuple[str, int]) -> SimpleNamespace:
    """A zha library Group: members as (ieee, endpoint_id), the way GroupMember exposes them."""
    return SimpleNamespace(
        members=[SimpleNamespace(device=SimpleNamespace(ieee=ieee), endpoint_id=endpoint) for ieee, endpoint in members]
    )
