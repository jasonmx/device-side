from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.device_side.integrations.zha import zcl


@pytest.fixture(autouse=True)
async def unload_mock_zha_entries(hass):
    """Mark mocked ZHA entries not loaded before teardown, so HA doesn't import the real zha to unload them."""
    yield
    for entry in hass.config_entries.async_entries("zha"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def zha_groups(monkeypatch) -> dict:
    """The fake zha gateway's groups by ID; the gateway answers get_group from it."""
    groups: dict = {}
    monkeypatch.setattr(zcl, "gateway", lambda hass: SimpleNamespace(get_group=groups.get))
    return groups
