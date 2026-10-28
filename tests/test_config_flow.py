"""Tests for the single-instance config flow, its options and entry setup."""

import asyncio

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_set_domains_to_be_loaded, async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockModule, mock_integration

from custom_components.device_side.const import CONF_PREDICTED_STATE, DOMAIN, NAME
from custom_components.device_side.core.resolver import resolve
from custom_components.device_side.core.runtime import get_runtime

from .fixtures.zha import add_zha_entity


async def test_user_step_creates_entry(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}


async def test_second_entry_aborts(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_entry_loads_and_unloads(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_an_integration_stuck_in_setup_does_not_hold_device_side_back(hass: HomeAssistant):
    """HA holds an integration's setup until each of its after_dependencies being set up has finished. A ZHA that
    never finishes must leave device_side's actions up, refusing only ZHA's targets."""
    setting_up = asyncio.Event()

    async def hang(hass, config):
        setting_up.set()
        await asyncio.Event().wait()

    mock_integration(hass, MockModule("zha", async_setup=hang))
    async_set_domains_to_be_loaded(hass, {"zha", DOMAIN})  # as bootstrap does: HA waits only on these
    zha_setup = hass.async_create_task(async_setup_component(hass, "zha", {}))
    await setting_up.wait()
    zha = MockConfigEntry(domain="zha")
    zha.add_to_hass(hass)
    zha.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)

    try:
        async with asyncio.timeout(5):
            assert await hass.config_entries.async_setup(entry.entry_id)
        assert hass.services.has_service(DOMAIN, "turn_on_for")
        add_zha_entity(hass, zha, "light.a")
        assert resolve(hass, get_runtime(hass).registry, "light.a") == "integration_not_loaded"
    finally:
        zha_setup.cancel()


async def test_predicted_state_is_on_for_an_entry_without_options(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert get_runtime(hass).predicted_state is True


async def test_saving_the_option_reloads_the_entry_with_it(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({}) == {CONF_PREDICTED_STATE: True}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_PREDICTED_STATE: False})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_PREDICTED_STATE: False}
    assert entry.state is ConfigEntryState.LOADED
    assert get_runtime(hass).predicted_state is False

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({}) == {CONF_PREDICTED_STATE: False}
