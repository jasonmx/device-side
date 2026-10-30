"""Hue lower_brightness: the end point with the time left, or a soft off at 0 %."""

import pytest

from .conftest import SENT, SOFT_OFF_3S, fade_put, lamp, mixed_room
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production")


@pytest.mark.parametrize(
    ("data", "put"),
    [
        pytest.param({}, SOFT_OFF_3S, id="to_zero_is_a_plain_soft_off"),
        pytest.param({"limit": 20}, fade_put(20.0, 2000), id="to_a_limit"),
    ],
)
async def test_writes_the_end_point_with_the_time_left(hass, bridge, data, put):
    entity_id = await lamp(hass, bridge)

    response = await call(hass, "lower_brightness", {"entity_id": entity_id, **data})

    assert response == {entity_id: SENT}
    assert bridge.puts == [("light/light-1", put)]


async def test_already_past_the_limit_nothing_is_sent(hass, bridge):
    entity_id = await lamp(hass, bridge, brightness_pct=20.0)

    response = await call(hass, "lower_brightness", {"entity_id": entity_id, "limit": 30})

    assert response == {entity_id: {"status": "unchanged", "integration": "hue", "detail": "at_limit"}}
    assert bridge.puts == []


async def test_down_from_off_is_at_the_limit(hass, bridge):
    entity_id = await lamp(hass, bridge, state="off")

    response = await call(hass, "lower_brightness", {"entity_id": entity_id})

    assert response[entity_id]["detail"] == "at_limit"


async def test_room_down_leaves_its_off_lights_out(hass, bridge, clock):
    # Only the lit light sets the duration and is predicted; the off one stays off and out of the average.
    entity_id = await mixed_room(hass, bridge, 80.0, None)
    await call(hass, "lower_brightness", {"entity_id": entity_id, "limit": 20})
    clock.now += 1.5

    response = await call(hass, "get_attributes", {"entity_id": [entity_id, "light.two"]})

    assert bridge.puts == [("grouped_light/grouped-1", fade_put(20.0, 3000))]
    assert response["light.room"]["brightness"] == 50.0
    assert response["light.two"]["brightness"] == 40.0
