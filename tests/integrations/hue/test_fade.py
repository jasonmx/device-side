"""Hue raise_brightness and lower_brightness share their fade: predictions per light, rooms, and what a stop, a write
or a report from elsewhere does to the next move."""

import pytest
from aiohue.v2.controllers.events import EventType
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.integrations.hue.transition_cache import transition_cache

from .conftest import fade_put, lamp, mixed_room, percent, room
from ...conftest import call, refusal
from ...fixtures.hue import add_hue_entity, hue_entry

pytestmark = pytest.mark.usefixtures("setup_production")


@pytest.mark.parametrize(("target", "path"), [("light", "light/light-1"), ("room", "grouped_light/grouped-1")])
async def test_move_after_a_stop_continues_from_where_it_halted(hass, bridge, clock, target, path):
    # The bridge reports the end value at once; the next move must start from the predicted one.
    entity_id = await (lamp if target == "light" else room)(hass, bridge, brightness_pct=20.0)
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    hass.states.async_set(entity_id, "on", {**hass.states.get(entity_id).attributes, "brightness": 255})
    clock.now += 3

    await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 5
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})

    assert bridge.puts[1] == (path, {"dimming_delta": {"action": "stop"}})
    assert bridge.puts[2] == (path, fade_put(100.0, 5000, on=True))  # from 50 %


async def test_a_refused_move_is_rejected_and_not_cached(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    bridge.failing.add("light-1")

    with pytest.raises(HomeAssistantError):
        await call(hass, "raise_brightness", {"entity_id": entity_id})
    bridge.failing.clear()
    clock.now += 1
    await call(hass, "raise_brightness", {"entity_id": entity_id})

    # Started from HA's 20 %, not from a phantom move's prediction.
    assert bridge.puts[-1] == ("light/light-1", fade_put(100.0, 4000, on=True))


async def test_light_without_dimming_drops_brightness_fields(hass, bridge):
    entity_id = await lamp(hass, bridge, brightness=None, mirek=None)

    response = await call(hass, "raise_brightness", {"entity_id": entity_id})

    # The adapter drops brightness for a non-dimmable light; nothing is sent.
    assert response == {entity_id: {"status": "unchanged", "integration": "hue", "detail": "fields_dropped"}}
    assert bridge.puts == []


@pytest.mark.parametrize("action", ["raise_saturation", "lower_saturation", "raise_hue", "lower_hue"])
async def test_color_actions_have_no_hue_adapter(hass, bridge, action):
    # Saturation waits for 7c2; hue has no fade the bridge runs alone.
    entity_id = await lamp(hass, bridge)

    assert await refusal(hass, action, {"entity_id": entity_id}) == "no_adapter"
    assert bridge.puts == []


@pytest.mark.parametrize("action", ["raise_brightness", "lower_brightness", "stop"])
async def test_resource_missing_from_the_bridge_is_rejected(hass, bridge, action):
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.gone", "light-gone", state="on")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, action, {"entity_id": "light.gone"})

    assert raised.value.translation_placeholders["summary"] == "light.gone: not_on_bridge"


@pytest.mark.parametrize("action", ["raise_brightness", "lower_brightness", "stop"])
async def test_v1_bridge_is_refused(hass, bridge, action):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge, api_version=1)
    add_hue_entity(hass, entry, "light.lamp", "light-1")

    assert await refusal(hass, action, {"entity_id": "light.lamp"}) == "bridge_v1"


@pytest.mark.parametrize("target", ["light", "room"])
async def test_get_attributes_predicts_brightness_mid_move(hass, bridge, clock, target):
    # hue_dimmer RELEASE_CHECKLIST §4.2: the bridge reports the end value; get_attributes reports the predicted one.
    if target == "light":
        entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    else:
        entity_id = await room(hass, bridge, brightness_pct=20.0)
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 3

    response = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response[entity_id]["brightness"] == 50.0


@pytest.mark.parametrize("stop_first", [False, True])
async def test_a_light_moved_mid_room_move_starts_where_it_is(hass, bridge, clock, stop_first):
    # The bridge already reports the room's end value for the light; its own prediction says 60 %.
    entity_id = await mixed_room(hass, bridge, 100.0, 100.0)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 10})
    hass.states.async_set("light.one", "off", {})
    clock.now += 4
    if stop_first:
        await call(hass, "stop", {"entity_id": "light.one"})
        clock.now += 2

    await call(hass, "raise_brightness", {"entity_id": "light.one", "sweep_time": 10})

    assert bridge.puts[-1] == ("light/one", fade_put(100.0, 4000, on=True))


async def test_room_reads_a_light_moved_on_its_own(hass, bridge, clock):
    entity_id = await mixed_room(hass, bridge, 40.0, 40.0)
    await call(hass, "raise_brightness", {"entity_id": "light.one", "sweep_time": 10})
    clock.now += 3

    response = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response["light.room"]["brightness"] == 55.0


async def test_a_change_from_elsewhere_mid_move_starts_the_next_move_from_it(hass, bridge, clock):
    # The Hue app turns the light off 3 s into a 20 % to 100 % fade: the next move starts from off, not the predicted
    # 50 %.
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 3
    bridge.api.events.emit(EventType.RESOURCE_UPDATED, {"id": "light-1", "type": "light", "on": {"on": False}})
    hass.states.async_set(entity_id, "off", {})
    await hass.async_block_till_done()

    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})

    assert bridge.puts[-1] == ("light/light-1", fade_put(100.0, 10000, on=True))


async def test_a_late_stop_report_keeps_the_prediction(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 3
    await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 5
    bridge.api.events.emit(
        EventType.RESOURCE_UPDATED, {"id": "light-1", "type": "light", "dimming": {"brightness": 50.2}}
    )
    await hass.async_block_till_done()

    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 10})

    assert bridge.puts[-1] == ("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 5000}})  # from 50 %


@pytest.mark.parametrize(
    ("service", "data"),
    [
        pytest.param("set_attributes", {"brightness": 80}, id="set_attributes"),
        pytest.param("turn_on", {}, id="ha_light_call"),
    ],
)
async def test_a_write_mid_move_starts_the_next_move_from_the_report(hass, bridge, clock, service, data):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    async_mock_service(hass, "light", "turn_on")
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 3
    if service == "turn_on":
        await hass.services.async_call("light", "turn_on", {"entity_id": entity_id}, blocking=True)
    else:
        await call(hass, service, {"entity_id": entity_id, **data})
    hass.states.async_set(entity_id, "on", {"brightness": percent(80.0)})

    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 10})

    assert bridge.puts[-1] == ("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 8000}})


async def test_the_fade_is_timed_from_when_the_write_was_sent(hass, bridge, clock):
    # The bridge starts the fade once it has the write; its reply comes back later.
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)
    request = bridge.api.request

    async def slow(*args, **kwargs):
        clock.now += 0.5
        return await request(*args, **kwargs)

    bridge.api.request = slow
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})

    assert transition_cache(hass).value("light-1", "brightness", 0.0) == pytest.approx(25.0)
