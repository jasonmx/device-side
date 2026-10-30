"""ZHA raise_hue: EnhancedMoveHue up, a cycle at a rate the bulb runs until a stop."""

import pytest

from custom_components.device_side.integrations.zha import zcl
from custom_components.device_side.integrations.zha.fade import hue_moves

from .conftest import SENT, bulb, sent, unchanged
from ...conftest import call

pytestmark = pytest.mark.usefixtures("setup_production", "clock", "bulbs")


async def test_a_cycle_in_the_sweep_time(hass, commands):
    bulb(hass)

    assert await call(hass, "raise_hue", {"entity_id": "light.bulb"}) == {"light.bulb": SENT}
    assert sent(commands) == [(0x0300, 0x41, {"move_mode": 1, "rate": 13107})]
    assert hue_moves(hass) == {"light.bulb"}


async def test_an_off_light_is_unchanged(hass, commands):
    bulb(hass, state="off")

    assert await call(hass, "raise_hue", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("off")}
    assert not commands


@pytest.mark.parametrize(
    ("sweep_time", "rate", "clamped_to"),
    [
        pytest.param(0.5, 65535, 1.0, id="under_a_second"),
        pytest.param(1.0, 65535, None, id="one_second"),
        pytest.param(65535, 1, None, id="the_longest_cycle"),
        pytest.param(70000, 1, 65535.0, id="over_the_longest_cycle"),
    ],
)
async def test_a_cycle_outside_1_to_65535_s_is_clamped(hass, commands, sweep_time, rate, clamped_to):
    bulb(hass)

    response = await call(hass, "raise_hue", {"entity_id": "light.bulb", "sweep_time": sweep_time})

    assert sent(commands) == [(0x0300, 0x41, {"move_mode": 1, "rate": rate})]
    expected = SENT if clamped_to is None else {**SENT, "clamped_to": clamped_to}
    assert response == {"light.bulb": expected}


async def test_dropped_without_enhanced_hue(hass, commands):
    zcl.enhanced_hue.return_value = False
    bulb(hass)

    assert await call(hass, "raise_hue", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("fields_dropped")}
    assert not commands
