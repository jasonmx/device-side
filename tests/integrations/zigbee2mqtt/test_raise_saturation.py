"""Zigbee2MQTT raise_saturation: a color at the current hue with the end saturation, and its color brought in line."""

import pytest

from custom_components.device_side.core.transition import SATURATION
from custom_components.device_side.integrations.zigbee2mqtt.fade import transition_cache

from .conftest import GET, SENT, SET, commands, group, light, unchanged
from ...conftest import advance, call, wall_clock_now

pytestmark = pytest.mark.usefixtures("setup_production", "clock")


@pytest.mark.parametrize(
    ("data", "payload"),
    [
        pytest.param({}, {"color": {"hue": 200.0, "saturation": 100.0}, "transition": 2.0}, id="at_the_current_hue"),
        pytest.param(
            {"limit": 80, "sweep_time": 10},
            {"color": {"hue": 200.0, "saturation": 80.0}, "transition": 2.0},
            id="to_a_limit",
        ),
    ],
)
async def test_publishes_the_end_point_with_the_time_left(hass, broker, data, payload):
    entity_id = light(hass, broker)

    response = await call(hass, "raise_saturation", {"entity_id": entity_id, **data})

    assert response == {entity_id: SENT}
    assert commands(broker) == [(SET, payload)]


async def test_an_off_light_is_unchanged(hass, broker):
    entity_id = light(hass, broker, state="off")

    response = await call(hass, "raise_saturation", {"entity_id": entity_id})

    assert response == {entity_id: unchanged("off")}
    assert commands(broker) == []


async def test_a_group_records_each_lit_member(hass, broker, clock):
    room = group(hass, broker, one={"hs": (200.0, 40.0)}, two={"hs": (200.0, 80.0)})

    await call(hass, "raise_saturation", {"entity_id": room})

    payload = {"color": {"hue": 200.0, "saturation": 100.0}, "transition": 2.0}
    assert commands(broker) == [("zigbee2mqtt/7/set", payload)]
    cache = transition_cache(hass)
    assert cache.value("light.one", SATURATION, 0) == 40.0
    assert cache.value("light.two", SATURATION, 0) == 80.0


async def test_the_color_is_brought_in_line_at_its_end(hass, broker):
    entity_id = light(hass, broker, color={"colorMode": 1})
    start = wall_clock_now()

    await call(hass, "raise_saturation", {"entity_id": entity_id})

    await advance(hass, start, 3.5)
    assert commands(broker)[1:] == [(GET, {"color": ""})]
