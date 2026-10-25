import pytest
from homeassistant.config_entries import ConfigEntryState


@pytest.fixture(autouse=True)
async def unload_mock_mqtt_entries(hass):
    """Mark mocked MQTT entries not loaded before teardown.

    Prevents HA from trying to import the real mqtt integration to unload them; the real
    integration is not set up in unit tests (no broker etc.).
    """
    yield
    for entry in hass.config_entries.async_entries("mqtt"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
