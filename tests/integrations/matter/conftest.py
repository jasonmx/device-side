import pytest
from homeassistant.config_entries import ConfigEntryState

from ...fixtures.matter import mock_chip  # noqa: F401 - re-exported as a fixture


@pytest.fixture(autouse=True)
async def unload_mock_matter_entries(hass):
    """Mark mocked Matter entries not loaded before teardown.

    Prevents HA from trying to import the real matter integration (which requires matter_server)
    to unload config entries created during the test.
    """
    yield
    for entry in hass.config_entries.async_entries("matter"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
