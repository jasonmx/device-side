"""ZHA raise_brightness: MoveToLevelWithOnOff to the limit, a light that is off put at the bottom first."""

import pytest

from custom_components.device_side.core.transition import BRIGHTNESS
from custom_components.device_side.integrations.zha.fade import transition_cache

from .conftest import BOTTOM, SENT, A, B, bulb, sent, to, unchanged
from ...conftest import call
from ...fixtures.zha import IEEE

pytestmark = pytest.mark.usefixtures("setup_production", "clock", "bulbs")


@pytest.mark.parametrize(
    ("data", "command"),
    [
        # From 60 %, the top of a 5 s sweep is 2 s away: the speed is the same wherever the move starts.
        pytest.param({}, (0x0008, 0x04, {"level": 254, "transition_time": 20}), id="to_the_top"),
        pytest.param({"limit": 80}, (0x0008, 0x04, {"level": 203, "transition_time": 10}), id="to_a_limit"),
    ],
)
async def test_sends_the_end_point_with_a_transition(hass, commands, data, command):
    bulb(hass)

    assert await call(hass, "raise_brightness", {"entity_id": "light.bulb", **data}) == {"light.bulb": SENT}
    assert sent(commands) == [command]
    where = {(c.data["ieee"], c.data["endpoint_id"], c.data["cluster_type"], c.data["command_type"]) for c in commands}
    assert where == {(IEEE, 11, "in", "server")}


async def test_from_off_starts_at_the_bottom(hass, commands):
    bulb(hass, state="off")

    await call(hass, "raise_brightness", {"entity_id": "light.bulb"})

    assert sent(commands) == [BOTTOM, (0x0008, 0x04, {"level": 254, "transition_time": 50})]


async def test_from_off_on_a_model_that_drops_levels_while_off_skips_the_bottom(hass, commands):
    """The E11-G13 jumps to full on a MoveToLevel while off, so it starts at its stored level instead."""
    bulb(hass, state="off", model="E11-G13")

    await call(hass, "raise_brightness", {"entity_id": "light.bulb"})

    assert sent(commands) == [(0x0008, 0x04, {"level": 254, "transition_time": 50})]


async def test_at_the_top_is_unchanged(hass, commands):
    bulb(hass, brightness=255)

    assert await call(hass, "raise_brightness", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("at_limit")}
    assert not commands


async def test_a_transition_longer_than_zcl_holds_runs_at_the_most(hass, commands):
    bulb(hass)

    await call(hass, "raise_brightness", {"entity_id": "light.bulb", "sweep_time": 100000})

    assert sent(commands) == [(0x0008, 0x04, {"level": 254, "transition_time": 0xFFFE})]


async def test_a_groups_members_get_one_groupcast_from_their_mean(hass, two_light_group, commands, group_commands):
    bulb(hass, "light.a", A, brightness=102)  # 40 %
    bulb(hass, "light.b", B, brightness=204)  # 80 %

    response = await call(hass, "raise_brightness", {"entity_id": "light.zha_group"})

    assert response == {"light.a": SENT, "light.b": SENT}
    # From the mean, 60 %: 2 s to the top.
    assert [command.data for command in group_commands] == [
        {"group": 2, "cluster_id": 0x0008, "command": 0x04, "args": [254, 20]}
    ]
    assert not commands
    cache = transition_cache(hass)
    assert cache.value("light.a", BRIGHTNESS, 0) == pytest.approx(40)
    assert cache.value("light.b", BRIGHTNESS, 0) == pytest.approx(80)


async def test_an_off_member_is_put_at_the_bottom_on_its_own(hass, two_light_group, commands, group_commands):
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B, state="off")

    await call(hass, "raise_brightness", {"entity_id": "light.zha_group"})

    assert to(commands) == [B]
    assert sent(commands) == [BOTTOM]
    assert len(group_commands) == 1
