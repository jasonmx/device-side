import pytest
from homeassistant.config_entries import ConfigEntryState


@pytest.fixture(autouse=True)
async def unload_mock_zha_entries(hass):
    """Mark mocked ZHA entries not loaded before teardown, so HA doesn't import the real zha to unload them."""
    yield
    for entry in hass.config_entries.async_entries("zha"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
