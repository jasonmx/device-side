import pytest
from homeassistant.config_entries import ConfigEntryState


@pytest.fixture(autouse=True)
async def unload_mock_shelly_entries(hass):
    """Mark mocked Shelly entries not loaded before teardown, so HA doesn't import the real integration to unload them.

    aioshelly stays out of the test environment on purpose: the integration must load without it.
    """
    yield
    for entry in hass.config_entries.async_entries("shelly"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
