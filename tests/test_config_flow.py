"""Tests for the single-instance config flow, its options and entry setup."""

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_side.const import CONF_PREDICTED_STATE, DOMAIN, NAME
from custom_components.device_side.core.runtime import get_runtime


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
