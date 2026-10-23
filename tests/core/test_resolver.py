"""entity_id -> Target: platform choice, detect precedence, unresolved reasons."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.device_side import features
from custom_components.device_side.core.registry import AdapterRegistry
from custom_components.device_side.core.resolver import resolve

from ..conftest import FAKE_PLATFORMS
from ..fixtures.fake import add_fake_entity, add_fake_native_group, add_switch_as_x, fake_config_entry

REGISTRY = AdapterRegistry(features.discover(), FAKE_PLATFORMS)


async def test_generic_platform_resolves(hass):
    entry = fake_config_entry(hass)
    add_fake_entity(hass, entry, "light.desk", "on")

    target = resolve(hass, REGISTRY, "light.desk", via_group="light.room")

    assert target.platform == "fake"
    assert target.domain == "light"
    assert target.state.state == "on"
    assert target.config_entry is entry
    assert target.via_group == "light.room"
    assert not target.is_group


async def test_detect_hook_wins_over_generic(hass):
    entry = fake_config_entry(hass)
    add_fake_entity(hass, entry, "light.lamp", identifier="special_0x01")

    assert resolve(hass, REGISTRY, "light.lamp").platform == "fake_special"


async def test_native_group_is_flagged(hass):
    entry = fake_config_entry(hass)
    add_fake_native_group(hass, entry, "light.fake_group", [])

    assert resolve(hass, REGISTRY, "light.fake_group").is_group


async def test_unresolved_reasons(hass):
    assert resolve(hass, REGISTRY, "light.ghost") == "not_in_registry"

    er.async_get(hass).async_get_or_create("light", "other", "x", suggested_object_id="other")
    assert resolve(hass, REGISTRY, "light.other") == "no_platform"

    entry = fake_config_entry(hass, ConfigEntryState.SETUP_ERROR)
    add_fake_entity(hass, entry, "light.broken")
    assert resolve(hass, REGISTRY, "light.broken") == "integration_not_loaded"


async def test_wrapper_resolves_to_the_wrapped_switch(hass):
    entry = fake_config_entry(hass)
    add_fake_entity(hass, entry, "switch.relay", "on")
    add_switch_as_x(hass, "light.relay", "switch.relay")

    target = resolve(hass, REGISTRY, "light.relay", via_group="light.room")

    assert (target.entity_id, target.domain, target.platform) == ("switch.relay", "switch", "fake")
    assert target.state.state == "on"
    assert target.via_wrapper == "light.relay"
    assert target.reported_id == "light.relay"
    assert target.via_group == "light.room"


async def test_unresolved_wrapper_reasons(hass):
    entry = fake_config_entry(hass)
    add_fake_entity(hass, entry, "switch.relay")

    add_switch_as_x(hass, "light.inverted", "switch.relay", invert=True)
    assert resolve(hass, REGISTRY, "light.inverted") == "inverted_wrapper"

    add_switch_as_x(hass, "light.outer", "light.inner")
    add_switch_as_x(hass, "light.inner", "switch.relay")
    assert resolve(hass, REGISTRY, "light.outer") == "not_addressable"

    add_switch_as_x(hass, "light.no_options", None)
    assert resolve(hass, REGISTRY, "light.no_options") == "not_in_registry"

    add_switch_as_x(hass, "light.dangling", "switch.ghost")
    assert resolve(hass, REGISTRY, "light.dangling") == "not_in_registry"
