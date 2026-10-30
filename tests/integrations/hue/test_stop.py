"""Hue stop: a dimming stop to the light or room, or a cut where our soft off runs, recorded where it halted."""

import pytest

from .conftest import SENT, STOP, lamp, mixed_room, report_off, room
from ...conftest import call, refusal

pytestmark = pytest.mark.usefixtures("setup_production")


async def test_stop_halts_a_room_with_one_write(hass, bridge):
    entity_id = await room(hass, bridge)

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("grouped_light/grouped-1", {"dimming_delta": {"action": "stop"}})]


async def test_stop_on_a_light_without_dimming_is_refused(hass, bridge):
    entity_id = await lamp(hass, bridge, brightness=None, mirek=None)

    assert await refusal(hass, "stop", {"entity_id": entity_id}) == "not_dimmable"


async def test_room_stop_mid_move_up_from_off_holds_each_light(hass, bridge, clock):
    # aiohue still shows both lights off; they count as lit because they are still moving.
    entity_id = await mixed_room(hass, bridge, None, None)
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 3
    await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 10

    response = await call(hass, "get_attributes", {"entity_id": [entity_id, "light.one"]})

    assert bridge.puts[1] == ("grouped_light/grouped-1", STOP)
    assert response["light.one"]["brightness"] == 30.0
    assert response["light.room"]["brightness"] == 30.0


async def test_stop_cuts_our_soft_off_with_on_and_the_predicted_brightness(hass, bridge, clock):
    # The bridge refuses a dimming stop during a soft off; on: true with a brightness and no duration ends it there.
    entity_id = await lamp(hass, bridge, brightness_pct=100.0)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 10})
    report_off(bridge, "light-1")
    hass.states.async_set(entity_id, "off", {})
    clock.now += 3

    response = await call(hass, "stop", {"entity_id": entity_id})
    clock.now += 10
    read = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts[1] == ("light/light-1", {"on": {"on": True}, "dimming": {"brightness": 70.0}})
    assert read[entity_id]["brightness"] == 70.0


async def test_stop_cuts_a_rooms_soft_off_light_by_light(hass, bridge, clock):
    # Measured on a single light only, so each light gets its own write at its own prediction.
    entity_id = await mixed_room(hass, bridge, 100.0, 50.0)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 10})
    report_off(bridge, "one", "two")
    clock.now += 2.5  # 7.5 s from the average 75 %: a third of the way down for each light

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts[0] == ("grouped_light/grouped-1", {"on": {"on": False}, "dynamics": {"duration": 7500}})
    assert sorted(bridge.puts[1:]) == [
        ("light/one", {"on": {"on": True}, "dimming": {"brightness": pytest.approx(200 / 3)}}),
        ("light/two", {"on": {"on": True}, "dimming": {"brightness": pytest.approx(100 / 3)}}),
    ]


async def test_room_cut_stops_a_light_moving_on_its_own(hass, bridge, clock):
    # One light turned back up mid soft off isn't fading off: it takes the dimming stop, not the cut.
    entity_id = await mixed_room(hass, bridge, 100.0, 100.0)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 10})
    report_off(bridge, "one", "two")
    clock.now += 4
    await call(hass, "raise_brightness", {"entity_id": "light.one", "sweep_time": 10})
    clock.now += 1

    await call(hass, "stop", {"entity_id": entity_id})

    assert sorted(bridge.puts[2:]) == [
        ("light/one", STOP),
        ("light/two", {"on": {"on": True}, "dimming": {"brightness": pytest.approx(50.0)}}),
    ]


@pytest.mark.parametrize("target", ["light", "room"])
async def test_stop_on_an_off_light_sends_nothing(hass, bridge, target):
    # Off, or fading off from elsewhere (the bridge reports off at the start): nothing to predict or stop.
    entity_id = await (lamp if target == "light" else room)(hass, bridge, state="off")

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response == {entity_id: {"status": "unchanged", "integration": "hue", "detail": "off"}}
    assert bridge.puts == []


async def test_stop_after_our_soft_off_ends_sends_nothing(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=100.0)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 2})
    report_off(bridge, "light-1")
    hass.states.async_set(entity_id, "off", {})
    clock.now += 3

    response = await call(hass, "stop", {"entity_id": entity_id})

    assert response[entity_id]["detail"] == "off"
    assert bridge.puts == [("light/light-1", {"on": {"on": False}, "dynamics": {"duration": 2000}})]
