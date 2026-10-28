import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.device_side.integrations.zigbee2mqtt import bridge, read

from ...fixtures.z2m import IEEE, INFO, Broker


@pytest.fixture(autouse=True)
async def unload_mock_mqtt_entries(hass):
    """Mark mocked MQTT entries not loaded before teardown.

    Prevents HA from trying to import the real mqtt integration to unload them; the real
    integration is not set up in unit tests (no broker etc.).
    """
    yield
    for entry in hass.config_entries.async_entries("mqtt"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def broker(hass, monkeypatch):
    fake = Broker()
    fake.retained[INFO] = {"config": {"devices": {IEEE: {"friendly_name": "bulb"}}, "groups": {}}}
    monkeypatch.setattr(bridge.mqtt, "async_subscribe", fake.subscribe)
    monkeypatch.setattr(bridge, "_RETAINED_TIMEOUT_S", 0.01)
    monkeypatch.setattr(bridge, "_REPLY_TIMEOUT_S", 0.01)
    monkeypatch.setattr(read, "_REPLY_TIMEOUT_S", 0.01)
    hass.services.async_register("mqtt", "publish", fake.publish)
    return fake
