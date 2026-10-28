"""ZHA stop: level Stop to each lit light, StopMoveStep where a color move of ours runs, the halt recorded, and a
refresh at once."""

import probatio
import pytest
from homeassistant.core import Context, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.const import DOMAIN
from custom_components.device_side.core.transition import BRIGHTNESS, SATURATION
from custom_components.device_side.integrations.zha.move import hue_moves, transition_cache

from .conftest import SENT, A, B, bulb, sent, unchanged
from ...conftest import advance, call, wall_clock_now

pytestmark = pytest.mark.usefixtures("setup_production", "clock")

LEVEL_STOP = (0x0008, 0x03, {})
STOP_MOVE_STEP = (0x0300, 0x47, {"options_mask": 0, "options_override": 0})


@pytest.fixture
def commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_cluster_command")


@pytest.fixture(autouse=True)
def zcl_reads(bulbs):
    return bulbs


async def test_a_lit_light_gets_level_stop_and_a_refresh_at_once(hass, commands, refreshes):
    bulb(hass)

    assert await call(hass, "stop", {"entity_id": "light.bulb"}) == {"light.bulb": SENT}
    assert sent(commands) == [LEVEL_STOP]
    assert [refresh.data for refresh in refreshes] == [{"entity_id": "light.bulb"}]


async def test_a_brightness_move_halts_where_it_is_predicted(hass, commands, clock):
    bulb(hass)
    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})
    clock.now += 1

    await call(hass, "stop", {"entity_id": "light.bulb"})

    assert sent(commands)[1:] == [LEVEL_STOP]
    cache = transition_cache(hass)
    assert cache.halted("light.bulb", BRIGHTNESS)
    assert cache.value("light.bulb", BRIGHTNESS, 0) == pytest.approx(80)


async def test_a_saturation_move_also_gets_stop_move_step(hass, commands, clock):
    bulb(hass)
    await call(hass, "move", {"entity_id": "light.bulb", "saturation": "up"})
    clock.now += 1

    await call(hass, "stop", {"entity_id": "light.bulb"})

    assert sent(commands)[1:] == [STOP_MOVE_STEP, LEVEL_STOP]
    assert transition_cache(hass).value("light.bulb", SATURATION, 0) == pytest.approx(80)


async def test_a_hue_cycle_gets_stop_move_step_and_ends(hass, commands):
    bulb(hass)
    await call(hass, "move", {"entity_id": "light.bulb", "hue": "up"})

    await call(hass, "stop", {"entity_id": "light.bulb"})

    assert sent(commands)[1:] == [STOP_MOVE_STEP, LEVEL_STOP]
    assert hue_moves(hass) == set()


async def test_no_stop_move_step_for_a_light_without_color(hass, commands):
    bulb(hass, modes=["color_temp"])
    hue_moves(hass).add("light.bulb")

    await call(hass, "stop", {"entity_id": "light.bulb"})

    assert sent(commands) == [LEVEL_STOP]


async def test_a_halted_soft_off_keeps_the_light_on(hass, commands, clock):
    """The stop cancels the restore: the light stays on at the halted level, as on Hue."""
    bulb(hass)
    start = wall_clock_now()
    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "down"})
    clock.now += 1
    hass.states.async_set("light.bulb", "off", {"supported_color_modes": ["color_temp", "xy"]})  # reported early

    assert await call(hass, "stop", {"entity_id": "light.bulb"}) == {"light.bulb": SENT}
    await advance(hass, start, 10)

    assert sent(commands)[1:] == [LEVEL_STOP]
    assert transition_cache(hass).value("light.bulb", BRIGHTNESS, 0) == pytest.approx(40)


async def test_an_off_light_is_unchanged(hass, commands, refreshes):
    bulb(hass, state="off")

    assert await call(hass, "stop", {"entity_id": "light.bulb"}) == {"light.bulb": unchanged("off")}
    assert not commands
    assert not refreshes


async def test_a_groups_lit_members_get_one_groupcast(hass, two_light_group, commands, group_commands):
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B)

    assert await call(hass, "stop", {"entity_id": "light.zha_group"}) == {"light.a": SENT, "light.b": SENT}
    assert [command.data for command in group_commands] == [
        {"group": 2, "cluster_id": 0x0008, "command": 0x03, "args": []}
    ]
    assert not commands


async def test_a_group_with_an_off_member_stops_each_lit_one(hass, two_light_group, commands, group_commands):
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B, state="off")

    response = await call(hass, "stop", {"entity_id": "light.zha_group"})

    assert response == {"light.a": SENT, "light.b": unchanged("off")}
    assert [command.data["ieee"] for command in commands] == [A]
    assert not group_commands


async def test_non_admin_caller_is_refused(hass, hass_read_only_user, refreshes):
    calls: list[ServiceCall] = []

    async def handler(service: ServiceCall) -> None:
        calls.append(service)

    schema = probatio.Schema({}, extra=probatio.ALLOW_EXTRA)
    async_register_admin_service(hass, "zha", "issue_zigbee_cluster_command", handler, schema)
    bulb(hass)

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "stop",
            {"entity_id": "light.bulb"},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )

    assert raised.value.translation_placeholders["summary"] == "light.bulb: admin_required"
    assert not calls
    assert not refreshes


async def test_a_failed_stop_rejects_and_keeps_the_move(hass, commands, clock):
    bulb(hass)
    await call(hass, "move", {"entity_id": "light.bulb", "brightness": "up"})

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("no route")

    hass.services.async_register("zha", "issue_zigbee_cluster_command", fail)
    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "stop", {"entity_id": "light.bulb"})

    assert raised.value.translation_placeholders["summary"] == "light.bulb: error"
    assert transition_cache(hass).running("light.bulb", BRIGHTNESS) is not None
