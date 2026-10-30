"""ZHA lower_saturation: MoveToColor, the xy of the current hue at the end saturation."""

import pytest

from .conftest import SENT, bulb, sent, unchanged, xy
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production", "clock", "bulbs")


async def test_sends_the_end_point_at_the_current_hue(hass, commands):
    bulb(hass)

    response = await call(hass, "lower_saturation", {"entity_id": "light.bulb", "limit": 20, "sweep_time": 10})

    assert response == {"light.bulb": SENT}
    assert sent(commands) == [(0x0300, 0x07, {**xy(200, 20), "transition_time": 40})]


async def test_at_white_is_unchanged(hass, commands):
    bulb(hass, hs=(200.0, 0.0))

    assert await call(hass, "lower_saturation", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("at_limit")}
    assert not commands
