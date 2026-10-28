"""ZHA move: an end point with a transition per attribute, hue as an EnhancedMoveHue rate, the soft off's restore and
the end refresh."""

from unittest.mock import AsyncMock

import probatio
import pytest
from homeassistant.core import Context, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util.color import color_hs_to_xy
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.const import DOMAIN
from custom_components.device_side.core.transition import BRIGHTNESS, SATURATION
from custom_components.device_side.integrations.zha import zcl
from custom_components.device_side.integrations.zha.move import hue_moves, transition_cache

from .conftest import SENT, A, B, bulb, sent, to, unchanged
from ...conftest import advance, call, wall_clock_now
from ...fixtures.zha import IEEE

pytestmark = pytest.mark.usefixtures("setup_production", "clock")

BOTTOM = (0x0008, 0x00, {"level": 1, "transition_time": 0, "options_mask": 1, "options_override": 1})


@pytest.fixture
def commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_cluster_command")


@pytest.fixture(autouse=True)
def on_off_read(monkeypatch):
    """zcl.read_attributes, reading the light off: its soft off has run."""
    read = AsyncMock(return_value={zcl.ON_OFF: False})
    monkeypatch.setattr(zcl, "read_attributes", read)
    return read


@pytest.fixture(autouse=True)
def enhanced_hue(monkeypatch):
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(zcl, "enhanced_hue", check)
    return check


def xy(hue: float, saturation: float) -> dict:
    x, y = color_hs_to_xy(hue, saturation)
    return {"color_x": round(x * 65535), "color_y": round(y * 65535)}


@pytest.mark.parametrize(
    ("data", "command"),
    [
        # From 60 %, the top of a 5 s sweep is 2 s away: the speed is the same wherever the move starts.
        pytest.param({"brightness": "up"}, (0x0008, 0x04, {"level": 254, "transition_time": 20}), id="up_turns_on"),
        pytest.param(
            {"brightness": "down"}, (0x0008, 0x04, {"level": 0, "transition_time": 30}), id="down_to_zero_is_a_soft_off"
        ),
        pytest.param(
            {"brightness": "down", "brightness_limit": 20},
            (0x0008, 0x00, {"level": 51, "transition_time": 20}),
            id="down_to_a_limit",
        ),
        pytest.param(
            {"saturation": "up"},
            (0x0300, 0x07, {**xy(200, 100), "transition_time": 20}),
            id="saturation_at_the_current_hue",
        ),
        pytest.param(
            {"saturation": "down", "saturation_limit": 20, "sweep_time": 10},
            (0x0300, 0x07, {**xy(200, 20), "transition_time": 40}),
            id="saturation_to_a_limit",
        ),
        pytest.param({"hue": "up"}, (0x0300, 0x41, {"move_mode": 1, "rate": 13107}), id="hue_up_a_cycle_in_5_s"),
        pytest.param({"hue": "down", "sweep_time": 10}, (0x0300, 0x41, {"move_mode": 3, "rate": 6554}), id="hue_down"),
    ],
)
async def test_sends_the_end_point_with_a_transition(hass, commands, data, command):
    bulb(hass)

    assert await call(hass, "move", {"entity_id": "light.bulb", **data}) == {"light.bulb": SENT}
    assert sent(commands) == [command]
    where = {(c.data["ieee"], c.data["endpoint_id"], c.data["cluster_type"], c.data["command_type"]) for c in commands}
    assert where == {(IEEE, 11, "in", "server")}


async def test_brightness_and_saturation_are_separate_fades(hass, commands, clock):
    bulb(hass)

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up", "saturation": "up"})

    assert [command[:2] for command in sent(commands)] == [(0x0008, 0x04), (0x0300, 0x07)]
    clock.now += 1
    cache = transition_cache(hass)
    assert cache.value("light.bulb", BRIGHTNESS, 0) == pytest.approx(80)
    assert cache.value("light.bulb", SATURATION, 0) == pytest.approx(80)


async def test_up_from_off_starts_at_the_bottom(hass, commands):
    bulb(hass, state="off")

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})

    assert sent(commands) == [BOTTOM, (0x0008, 0x04, {"level": 254, "transition_time": 50})]


async def test_up_from_off_on_a_model_that_drops_levels_while_off_skips_the_bottom(hass, commands):
    """The E11-G13 jumps to full on a MoveToLevel while off, so it starts at its stored level instead."""
    bulb(hass, state="off", model="E11-G13")

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})

    assert sent(commands) == [(0x0008, 0x04, {"level": 254, "transition_time": 50})]


async def test_a_move_continues_from_the_predicted_value(hass, commands, clock):
    bulb(hass)
    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})
    clock.now += 1  # 80 %: HA still shows the 60 % it had

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down", "brightness_limit": 20})

    assert sent(commands)[-1] == (0x0008, 0x00, {"level": 51, "transition_time": 30})


async def test_soft_off_restores_the_start_level_once_the_light_reads_off(hass, commands, refreshes, on_off_read):
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down"})
    await advance(hass, start, 3.5)
    assert len(commands) == 1
    await advance(hass, start, 4.5)

    restore = (0x0008, 0x00, {"level": 152, "transition_time": 0, "options_mask": 1, "options_override": 1})
    assert sent(commands)[1:] == [restore]
    assert on_off_read.await_args.args[2:] == (zcl.ON_OFF_CLUSTER, (zcl.ON_OFF,))
    assert [refresh.data for refresh in refreshes] == [{"entity_id": "light.bulb"}]


async def test_no_restore_when_the_light_still_reads_on(hass, commands, refreshes, on_off_read):
    on_off_read.return_value = {zcl.ON_OFF: True}
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down"})
    await advance(hass, start, 4.5)

    assert len(commands) == 1
    assert len(refreshes) == 1


async def test_a_failed_restore_still_refreshes(hass, commands, refreshes, on_off_read):
    on_off_read.side_effect = LookupError("no answer")
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down"})
    await advance(hass, start, 4.5)

    assert len(commands) == 1
    assert len(refreshes) == 1


async def test_no_restore_on_a_model_that_drops_levels_while_off(hass, commands, on_off_read):
    bulb(hass, model="E11-G13")
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down"})
    await advance(hass, start, 4.5)

    assert len(commands) == 1
    on_off_read.assert_not_awaited()


async def test_a_new_move_cancels_the_restore(hass, commands, on_off_read, clock):
    bulb(hass)
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down"})
    clock.now += 1

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})
    await advance(hass, start, 10)

    assert [command[:2] for command in sent(commands)] == [(0x0008, 0x04), (0x0008, 0x04)]
    on_off_read.assert_not_awaited()


async def test_end_refresh_once_the_fade_has_run(hass, commands, refreshes):
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": "light.bulb", "saturation": "up"})
    await advance(hass, start, 2.5)
    assert not refreshes
    await advance(hass, start, 3.5)

    assert [refresh.data for refresh in refreshes] == [{"entity_id": "light.bulb"}]


async def test_a_failed_refresh_is_only_logged(hass, commands, caplog):
    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("unavailable")

    hass.services.async_register("homeassistant", "update_entity", fail)
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "move", {"entity_id": "light.bulb", "saturation": "up"})
    await advance(hass, start, 3.5)

    assert len(commands) == 1


async def test_a_hue_move_is_tracked_and_a_saturation_move_ends_it(hass, commands):
    bulb(hass)

    await call(hass, "move", {"entity_id": "light.bulb", "hue": "up"})
    assert hue_moves(hass) == {"light.bulb"}

    await call(hass, "move", {"entity_id": "light.bulb", "saturation": "up"})
    assert hue_moves(hass) == set()


@pytest.mark.parametrize(
    ("sweep_time", "rate", "clamped_to"),
    [
        pytest.param(0.5, 65535, 1.0, id="under_a_second"),
        pytest.param(1.0, 65535, None, id="one_second"),
        pytest.param(65535, 1, None, id="the_longest_cycle"),
        pytest.param(70000, 1, 65535.0, id="over_the_longest_cycle"),
    ],
)
async def test_a_hue_cycle_outside_1_to_65535_s_is_clamped(hass, commands, sweep_time, rate, clamped_to):
    bulb(hass)

    response = await call(hass, "move", {"entity_id": "light.bulb", "hue": "up", "sweep_time": sweep_time})

    assert sent(commands) == [(0x0300, 0x41, {"move_mode": 1, "rate": rate})]
    expected = SENT if clamped_to is None else {**SENT, "clamped_to": clamped_to}
    assert response == {"light.bulb": expected}


async def test_a_transition_longer_than_zcl_holds_runs_at_the_most(hass, commands):
    bulb(hass)

    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up", "sweep_time": 100000})

    assert sent(commands) == [(0x0008, 0x04, {"level": 254, "transition_time": 0xFFFE})]


async def test_hue_is_dropped_without_enhanced_hue(hass, commands, enhanced_hue):
    enhanced_hue.return_value = False
    bulb(hass)

    assert await call(hass, "move", {"entity_id": "light.bulb", "hue": "up"}) == {
        "light.bulb": unchanged("fields_dropped")
    }
    response = await call(hass, "move", {"entity_id": "light.bulb", "hue": "up", "brightness": "up"})

    assert response == {"light.bulb": {**SENT, "detail": "fields_dropped"}}
    assert [command[:2] for command in sent(commands)] == [(0x0008, 0x04)]


@pytest.mark.parametrize(
    ("data", "state", "detail"),
    [
        pytest.param({"brightness": "up"}, {"brightness": 255}, "at_limit", id="up_at_the_top"),
        pytest.param({"brightness": "down"}, {"state": "off"}, "off", id="down_while_off"),
        pytest.param({"saturation": "up"}, {"state": "off"}, "off", id="saturation_while_off"),
        pytest.param({"hue": "up"}, {"state": "off"}, "off", id="hue_while_off"),
        pytest.param({"saturation": "down"}, {"hs": (200.0, 0.0)}, "at_limit", id="saturation_at_white"),
        pytest.param({"brightness": "down", "saturation": "down"}, {"state": "off"}, "off", id="off_explains_both"),
    ],
)
async def test_nothing_to_move_is_unchanged(hass, commands, data, state, detail):
    bulb(hass, **state)

    assert await call(hass, "move", {"entity_id": "light.bulb", **data}) == {"light.bulb": unchanged(detail)}
    assert not commands


async def test_non_admin_caller_is_refused(hass, hass_read_only_user):
    calls: list[ServiceCall] = []

    async def handler(service: ServiceCall) -> None:
        calls.append(service)

    schema = probatio.Schema({}, extra=probatio.ALLOW_EXTRA)
    async_register_admin_service(hass, "zha", "issue_zigbee_cluster_command", handler, schema)
    bulb(hass)

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "move",
            {"entity_id": "light.bulb", "brightness": "up"},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )

    assert raised.value.translation_placeholders["summary"] == "light.bulb: admin_required"
    assert not calls
    assert not transition_cache(hass).tracks("light.bulb", BRIGHTNESS)


async def test_a_failed_command_rejects_and_keeps_no_prediction(hass):
    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("no route")

    hass.services.async_register("zha", "issue_zigbee_cluster_command", fail)
    bulb(hass)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})

    assert raised.value.translation_placeholders["summary"] == "light.bulb: error"
    assert not transition_cache(hass).tracks("light.bulb", BRIGHTNESS)


async def test_a_groups_members_get_one_groupcast_from_their_mean(hass, two_light_group, commands, group_commands):
    bulb(hass, "light.a", A, brightness=102)  # 40 %
    bulb(hass, "light.b", B, brightness=204)  # 80 %

    response = await call(hass, "move", {"entity_id": "light.zha_group", "brightness": "up"})

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

    await call(hass, "move", {"entity_id": "light.zha_group", "brightness": "up"})

    assert to(commands) == [B]
    assert sent(commands) == [BOTTOM]
    assert len(group_commands) == 1


async def test_a_move_that_passes_an_off_member_by_goes_to_each_lit_one(
    hass, two_light_group, commands, group_commands
):
    """A soft off groupcast would still drop the off member's stored level."""
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B, state="off")

    response = await call(hass, "move", {"entity_id": "light.zha_group", "brightness": "down"})

    assert response == {"light.a": SENT, "light.b": unchanged("off")}
    assert to(commands) == [A]
    assert not group_commands


async def test_a_failed_groupcast_rejects_its_members(hass, two_light_group):
    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("no route")

    hass.services.async_register("zha", "issue_zigbee_group_command", fail)
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "move", {"entity_id": "light.zha_group", "brightness": "up"})

    assert raised.value.translation_placeholders["summary"] == "light.a: error, light.b: error"
