"""ZHA lower_brightness: MoveToLevel to a limit, or a soft off at 0 % with the start level restored once the light
reads off."""

import pytest

from custom_components.device_side.integrations.zha import zcl

from .conftest import RESTORE_60, SENT, A, B, bulb, on_off_reads, sent, to, unchanged
from ...conftest import advance, call, wall_clock_now

pytestmark = pytest.mark.usefixtures("setup_production", "clock", "bulbs")


@pytest.fixture(autouse=True)
def on_off_read(bulbs):
    return bulbs.read


@pytest.mark.parametrize(
    ("data", "command"),
    [
        pytest.param({}, (0x0008, 0x04, {"level": 0, "transition_time": 30}), id="to_zero_is_a_soft_off"),
        pytest.param({"limit": 20}, (0x0008, 0x00, {"level": 51, "transition_time": 20}), id="to_a_limit"),
    ],
)
async def test_sends_the_end_point_with_a_transition(hass, commands, data, command):
    bulb(hass)

    assert await call(hass, "lower_brightness", {"entity_id": "light.bulb", **data}) == {"light.bulb": SENT}
    assert sent(commands) == [command]


async def test_continues_from_the_predicted_value(hass, commands, clock):
    bulb(hass)
    await call(hass, "raise_brightness", {"entity_id": "light.bulb"})
    clock.now += 1  # 80 %: HA still shows the 60 % it had

    await call(hass, "lower_brightness", {"entity_id": "light.bulb", "limit": 20})

    assert sent(commands)[-1] == (0x0008, 0x00, {"level": 51, "transition_time": 30})


async def test_an_off_light_is_unchanged(hass, commands):
    bulb(hass, state="off")

    assert await call(hass, "lower_brightness", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("off")}
    assert not commands


async def test_soft_off_restores_the_start_level_once_the_light_reads_off(hass, commands, refreshes, on_off_read):
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await advance(hass, start, 3.5)
    assert len(commands) == 1
    await advance(hass, start, 4.5)

    assert sent(commands)[1:] == [RESTORE_60]
    assert on_off_read.await_args.args[2:] == (zcl.ON_OFF_CLUSTER, (zcl.ON_OFF,))
    assert [refresh.data for refresh in refreshes] == [{"entity_id": "light.bulb"}]


async def test_no_restore_when_the_light_still_reads_on(hass, commands, refreshes, bulbs):
    bulbs.on = True
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await advance(hass, start, 4.5)

    assert len(commands) == 1
    assert len(refreshes) == 1


async def test_a_failed_restore_still_refreshes(hass, commands, refreshes, on_off_read):
    on_off_read.side_effect = LookupError("no answer")
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await advance(hass, start, 4.5)

    assert len(commands) == 1
    assert len(refreshes) == 1


async def test_no_restore_on_a_model_that_drops_levels_while_off(hass, commands, on_off_read):
    bulb(hass, model="E11-G13")
    start = wall_clock_now()

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await advance(hass, start, 4.5)

    assert len(commands) == 1
    assert not on_off_reads(on_off_read)


async def test_a_raise_cancels_the_restore(hass, commands, on_off_read, clock):
    bulb(hass)
    start = wall_clock_now()
    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    clock.now += 1

    await call(hass, "raise_brightness", {"entity_id": "light.bulb"})
    await advance(hass, start, 10)

    assert [command[:2] for command in sent(commands)] == [(0x0008, 0x04), (0x0008, 0x04)]
    assert not on_off_reads(on_off_read)


async def test_a_lower_that_passes_an_off_member_by_goes_to_each_lit_one(
    hass, two_light_group, commands, group_commands
):
    """A soft off groupcast would still drop the off member's stored level."""
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B, state="off")

    response = await call(hass, "lower_brightness", {"entity_id": "light.zha_group"})

    assert response == {"light.a": SENT, "light.b": unchanged("off")}
    assert to(commands) == [A]
    assert not group_commands
