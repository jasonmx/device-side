"""ZHA lower_hue: EnhancedMoveHue down, a cycle at a rate the bulb runs until a stop."""

import pytest

from .conftest import SENT, bulb, sent
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production", "clock", "bulbs")


async def test_a_cycle_in_the_sweep_time(hass, commands):
    bulb(hass)

    assert await call(hass, "lower_hue", {"entity_id": "light.bulb", "sweep_time": 10}) == {"light.bulb": SENT}
    assert sent(commands) == [(0x0300, 0x41, {"move_mode": 3, "rate": 6554})]
