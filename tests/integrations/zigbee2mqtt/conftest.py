import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.device_side.integrations.zigbee2mqtt import bridge, read
from custom_components.device_side.integrations.zigbee2mqtt.fade import transition_cache

from ...fixtures.z2m import GROUPS, IEEE, INFO, Broker, add_z2m_entity, add_z2m_group, z2m_entry


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


DEVICES = "zigbee2mqtt/bridge/devices"
XY = ["color_temp", "xy"]
# A light's color cluster mid-hue-cycle: in hs mode (0), at x 0.3 and y 0.4.
COLOR = {"colorMode": 0, "currentX": 19661, "currentY": 26214}


class Clock:
    """A transition cache clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(hass, setup_production) -> Clock:
    clock = Clock()
    transition_cache(hass).clock = clock
    return clock


def light(
    hass,
    broker,
    entity_id: str = "light.lamp",
    ieee: str = IEEE,
    *,
    state: str = "on",
    brightness: int | None = 153,  # 60 %
    hs: tuple[float, float] | None = (200.0, 60.0),
    modes: list[str] | None = None,
    color_hs: bool = True,
    color: dict | None = None,
) -> str:
    """A Z2M color light HA lists with xy, whose definition exposes color_hs, answering color reads with COLOR."""
    name = entity_id.split(".")[1]
    entries = hass.config_entries.async_entries("mqtt")
    entry = entries[0] if entries else z2m_entry(hass)
    attributes: dict = {"supported_color_modes": XY if modes is None else modes}
    if state == "on":
        attributes |= {"brightness": brightness, "hs_color": hs}
    add_z2m_entity(hass, entry, entity_id, ieee=ieee, state=state, attributes=attributes, name=name)
    broker.devices[ieee] = (name, {"lightingColorCtrl": {**COLOR, **(color or {})}})
    broker.retained[INFO]["config"]["devices"].setdefault(ieee, {})
    features = [{"name": "state"}, {"name": "brightness"}] + ([{"name": "color_hs"}] if color_hs else [])
    device = {"ieee_address": ieee, "definition": {"exposes": [{"type": "light", "features": features}]}}
    broker.retained.setdefault(DEVICES, []).append(device)
    return entity_id


def group(hass, broker, **members: dict) -> str:
    """Z2M group 7, light.room, of light.one (0x01) and light.two (0x02), each set up by light() with its options."""
    for ieee, (name, options) in zip(("0x01", "0x02"), members.items(), strict=True):
        light(hass, broker, f"light.{name}", ieee, **options)
    add_z2m_group(hass, hass.config_entries.async_entries("mqtt")[0], "light.room", group_id=7, name="room")
    hass.states.async_set("light.room", "on", {"supported_color_modes": XY, "hs_color": (200.0, 60.0)})
    broker.retained[GROUPS] = [{"id": 7, "members": [{"ieee_address": "0x01"}, {"ieee_address": "0x02"}]}]
    return "light.room"


def commands(broker) -> list[tuple[str, dict]]:
    """Every command and get published to a light or group, leaving out bridge requests and reads."""
    return [
        (p["topic"], p["payload"])
        for p in broker.published
        if not p["topic"].startswith("zigbee2mqtt/bridge/") and "read" not in p["payload"]
    ]


SENT = {"status": "sent", "integration": "zigbee2mqtt"}
SET = f"zigbee2mqtt/{IEEE}/set"
GET = f"zigbee2mqtt/{IEEE}/get"
# An off light is put here first, so a fade from off starts at the bottom, not the level it kept.
BOTTOM = {"state": "ON", "brightness": 1, "transition": 0}


def unchanged(detail: str) -> dict:
    return {"status": "unchanged", "integration": "zigbee2mqtt", "detail": detail}
