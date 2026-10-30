"""Hue raise_brightness: the end point with the time left, turning the light on."""

import pytest

from .conftest import SENT, fade_put, lamp, mixed_room, room
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production")


@pytest.mark.parametrize(
    ("data", "put"),
    [
        pytest.param({}, fade_put(100.0, 2000, on=True), id="to_the_top_turns_on"),
        pytest.param({"limit": 80}, fade_put(80.0, 1000, on=True), id="to_a_limit"),
        pytest.param({"sweep_time": 10}, fade_put(100.0, 4000, on=True), id="sweep_time"),
        pytest.param({"sweep_time": 0.1}, fade_put(100.0, 40, on=True), id="shortest_sweep"),
    ],
)
async def test_writes_the_end_point_with_the_time_left(hass, bridge, data, put):
    # 60 % to the top of a 5 s sweep is 2 s: the speed is the same wherever the move starts.
    entity_id = await lamp(hass, bridge)

    response = await call(hass, "raise_brightness", {"entity_id": entity_id, **data})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("light/light-1", put)]


async def test_up_from_off_starts_at_the_bottom(hass, bridge):
    # HA shows no brightness for a light that is off, so the move takes the whole sweep from 0 %.
    entity_id = await lamp(hass, bridge, state="off")

    await call(hass, "raise_brightness", {"entity_id": entity_id})

    assert bridge.puts == [("light/light-1", fade_put(100.0, 5000, on=True))]


@pytest.mark.parametrize(
    ("brightness_pct", "data"),
    [
        pytest.param(99.9, {}, id="at_the_top"),
        pytest.param(80.0, {"limit": 70}, id="already_past_the_limit"),
    ],
)
async def test_at_the_limit_nothing_is_sent(hass, bridge, brightness_pct, data):
    entity_id = await lamp(hass, bridge, brightness_pct=brightness_pct)

    response = await call(hass, "raise_brightness", {"entity_id": entity_id, **data})

    assert response == {entity_id: {"status": "unchanged", "integration": "hue", "detail": "at_limit"}}
    assert bridge.puts == []


async def test_room_moves_with_one_grouped_light_write(hass, bridge):
    entity_id = await room(hass, bridge)

    response = await call(hass, "raise_brightness", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("grouped_light/grouped-1", fade_put(100.0, 2000, on=True))]


async def test_up_after_our_soft_off_starts_at_the_bottom(hass, bridge, clock):
    entity_id = await lamp(hass, bridge, brightness_pct=60.0)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "sweep_time": 5})
    hass.states.async_set(entity_id, "off", {})
    clock.now += 4

    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 5})

    assert bridge.puts[1] == ("light/light-1", fade_put(100.0, 5000, on=True))


async def test_get_attributes_predicts_a_room_moving_up_from_all_off(hass, bridge, clock):
    # aiohue still shows every light off until the bridge's event arrives; the room row is predicted anyway.
    entity_id = await room(hass, bridge, state="off")
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 4

    response = await call(hass, "get_attributes", {"entity_id": entity_id})

    assert response[entity_id]["brightness"] == 40.0


async def test_room_move_predicts_each_light(hass, bridge, clock):
    entity_id = await mixed_room(hass, bridge, 20.0, 60.0)
    await call(hass, "raise_brightness", {"entity_id": entity_id, "sweep_time": 10})
    clock.now += 3  # 6 s from the average 40 %: each light covers half of its own distance to 100 %

    response = await call(hass, "get_attributes", {"entity_id": [entity_id, "light.one", "light.two"]})

    assert bridge.puts == [("grouped_light/grouped-1", fade_put(100.0, 6000, on=True))]
    assert response["light.one"]["brightness"] == 60.0
    assert response["light.two"]["brightness"] == 80.0
    assert response["light.room"]["brightness"] == 70.0
