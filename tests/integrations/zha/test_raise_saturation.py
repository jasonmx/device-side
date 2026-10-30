"""ZHA raise_saturation: MoveToColor, the xy of the current hue at the end saturation, and the end refresh."""

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.device_side.integrations.zha.fade import hue_moves

from .conftest import SENT, bulb, sent, unchanged, xy
from ...conftest import advance, call, wall_clock_now

pytestmark = pytest.mark.usefixtures("setup_production", "clock", "bulbs")


async def test_sends_the_end_point_at_the_current_hue(hass, commands):
    bulb(hass)

    assert await call(hass, "raise_saturation", {"entity_id": "light.bulb"}) == {"light.bulb": SENT}
    assert sent(commands) == [(0x0300, 0x07, {**xy(200, 100), "transition_time": 20})]


async def test_an_off_light_is_unchanged(hass, commands):
    bulb(hass, state="off")

    assert await call(hass, "raise_saturation", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("off")}
    assert not commands


async def test_end_refresh_once_the_fade_has_run(hass, commands, refreshes):
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "raise_saturation", {"entity_id": "light.bulb"})
    await advance(hass, start, 2.5)
    assert not refreshes
    await advance(hass, start, 3.5)

    assert [refresh.data for refresh in refreshes] == [{"entity_id": "light.bulb"}]


async def test_a_failed_refresh_is_only_logged(hass, commands, caplog):
    caplog.set_level("DEBUG")

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("unavailable")

    hass.services.async_register("homeassistant", "update_entity", fail)
    bulb(hass)
    start = wall_clock_now()

    assert await call(hass, "raise_saturation", {"entity_id": "light.bulb"}) == {"light.bulb": SENT}
    await advance(hass, start, 3.5)

    assert "update_entity for light.bulb failed: unavailable" in caplog.text


async def test_ends_a_hue_cycle(hass, commands):
    bulb(hass)

    await call(hass, "raise_hue", {"entity_id": "light.bulb"})
    assert hue_moves(hass) == {"light.bulb"}

    await call(hass, "raise_saturation", {"entity_id": "light.bulb"})
    assert hue_moves(hass) == set()
