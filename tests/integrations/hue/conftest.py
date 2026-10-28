import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.device_side.integrations.hue.transition_cache import transition_cache

from ...fixtures.hue import HueBridge, add_hue_entity, add_hue_group, hue_entry, light_action


class Clock:
    """A transition cache clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(hass) -> Clock:
    clock = Clock()
    transition_cache(hass).clock = clock
    return clock


@pytest.fixture
def bridge() -> HueBridge:
    return HueBridge()


@pytest.fixture(autouse=True)
async def unload_mock_hue_entries(hass):
    """Mark mocked hue entries not loaded before teardown, so HA doesn't run the real hue unload on them."""
    yield
    for entry in hass.config_entries.async_entries("hue"):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def setup_room(hass, bridge):
    """Two lights on at 20 % in room-1, with a scene; the HA entities core's hue integration would make."""
    bridge.light("one", on=True, brightness=20.0)
    bridge.light("two", on=True, brightness=20.0)
    bridge.room("1", ["one", "two"], brightness=20.0)
    bridge.scene("scene-1", [light_action("one", on={"on": True})])
    entry = await hue_entry(hass, bridge)
    members = [
        add_hue_entity(hass, entry, f"light.{light_id}", light_id, state="on", attributes={"brightness": 51})
        for light_id in ("one", "two")
    ]
    add_hue_group(hass, entry, "light.room", "1", members)
    hass.states.async_set("light.room", "on", {"is_hue_group": True, "entity_id": members, "brightness": 51})
    add_hue_entity(hass, entry, "scene.relax", "scene-1")
    return entry


def light_event(light_id: str, *, brightness: float | None = None, on: bool | None = None, **extra) -> dict:
    event: dict = {"id": light_id, "type": "light", **extra}
    if brightness is not None:
        event["dimming"] = {"brightness": brightness}
    if on is not None:
        event["on"] = {"on": on}
    return event
