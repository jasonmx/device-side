"""Zigbee2MQTT raise_hue: Z2M's hue_move, a cycle red to yellow to green at a rate the bulb runs until a stop."""

import pytest

from .conftest import SENT, SET, commands, light, unchanged
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production", "clock")


async def test_a_cycle_in_the_sweep_time(hass, broker):
    entity_id = light(hass, broker)

    response = await call(hass, "raise_hue", {"entity_id": entity_id})

    assert response == {entity_id: SENT}
    assert commands(broker) == [(SET, {"hue_move": 51})]


async def test_an_off_light_is_unchanged(hass, broker):
    entity_id = light(hass, broker, state="off")

    response = await call(hass, "raise_hue", {"entity_id": entity_id})

    assert response == {entity_id: unchanged("off")}
    assert commands(broker) == []


@pytest.mark.parametrize(
    ("sweep_time", "rate", "clamped_to"),
    [(0.5, 254, 1.0), (1, 254, None), (10, 25, None), (254, 1, None), (300, 1, 254.0)],
)
async def test_sweep_time_outside_1_to_254_s_is_clamped_and_reported(hass, broker, sweep_time, rate, clamped_to):
    entity_id = light(hass, broker)

    response = await call(hass, "raise_hue", {"entity_id": entity_id, "sweep_time": sweep_time})

    assert response == {entity_id: SENT | ({"clamped_to": clamped_to} if clamped_to else {})}
    assert commands(broker) == [(SET, {"hue_move": rate})]
