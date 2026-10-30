"""Zigbee2MQTT lower_saturation: a color at the current hue with the end saturation."""

import pytest

from .conftest import SENT, SET, commands, light, unchanged
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production", "clock")


@pytest.mark.parametrize(
    ("data", "payload"),
    [
        pytest.param({}, {"color": {"hue": 200.0, "saturation": 0.0}, "transition": 3.0}, id="to_white"),
        pytest.param(
            {"limit": 20, "sweep_time": 10},
            {"color": {"hue": 200.0, "saturation": 20.0}, "transition": 4.0},
            id="to_a_limit",
        ),
    ],
)
async def test_publishes_the_end_point_with_the_time_left(hass, broker, data, payload):
    entity_id = light(hass, broker)

    response = await call(hass, "lower_saturation", {"entity_id": entity_id, **data})

    assert response == {entity_id: SENT}
    assert commands(broker) == [(SET, payload)]


@pytest.mark.parametrize(
    ("options", "data", "detail"),
    [
        pytest.param({"hs": (200.0, 20.0)}, {"limit": 20}, "at_limit", id="at_the_limit"),
        pytest.param({"state": "off"}, {}, "off", id="an_off_light"),
    ],
)
async def test_nothing_left_to_move_is_unchanged(hass, broker, options, data, detail):
    entity_id = light(hass, broker, **options)

    response = await call(hass, "lower_saturation", {"entity_id": entity_id, **data})

    assert response == {entity_id: unchanged(detail)}
    assert commands(broker) == []
