"""ZHA raise and lower share their fade: separate fades per attribute, failures, and the ramp fitted to a Level read."""

import probatio
import pytest
from homeassistant.core import Context, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service

from custom_components.device_side.const import DOMAIN
from custom_components.device_side.core.transition import BRIGHTNESS, SATURATION
from custom_components.device_side.integrations.zha.fade import transition_cache

from .conftest import RESTORE_60, SENT, A, B, bulb, on_off_reads, sent
from ...conftest import advance, call, wall_clock_now
from ...fixtures.zha import IEEE

pytestmark = pytest.mark.usefixtures("setup_production", "clock")


@pytest.fixture(autouse=True)
def on_off_read(bulbs):
    return bulbs.read


async def test_brightness_and_saturation_are_separate_fades(hass, commands, clock):
    bulb(hass)

    await call(hass, "raise_brightness", {"entity_id": "light.bulb"})
    await call(hass, "raise_saturation", {"entity_id": "light.bulb"})

    assert [command[:2] for command in sent(commands)] == [(0x0008, 0x04), (0x0300, 0x07)]
    clock.now += 1
    cache = transition_cache(hass)
    assert cache.value("light.bulb", BRIGHTNESS, 0) == pytest.approx(80)
    assert cache.value("light.bulb", SATURATION, 0) == pytest.approx(80)


async def test_a_move_of_another_attribute_keeps_the_soft_offs_restore(hass, commands, refreshes, on_off_read):
    bulb(hass)
    start = wall_clock_now()

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await call(hass, "lower_saturation", {"entity_id": "light.bulb"})
    await advance(hass, start, 4.5)

    assert sent(commands)[-1] == RESTORE_60
    assert len(on_off_reads(on_off_read)) == 1
    assert len(refreshes) == 2  # one per fade


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
            "raise_brightness",
            {"entity_id": "light.bulb"},
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
        await call(hass, "raise_brightness", {"entity_id": "light.bulb"})

    assert raised.value.translation_placeholders["summary"] == "light.bulb: error"
    assert not transition_cache(hass).tracks("light.bulb", BRIGHTNESS)


async def test_a_failed_groupcast_rejects_its_members(hass, two_light_group):
    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("no route")

    hass.services.async_register("zha", "issue_zigbee_group_command", fail)
    bulb(hass, "light.a", A)
    bulb(hass, "light.b", B)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "raise_brightness", {"entity_id": "light.zha_group"})

    assert raised.value.translation_placeholders["summary"] == "light.a: error, light.b: error"


def read_takes(bulbs, clock, seconds: float) -> None:
    """Each Level read takes `seconds` on the cache's clock."""
    answer = bulbs.read.side_effect

    async def slow(*args, **kwargs):
        clock.now += seconds
        return await answer(*args, **kwargs)

    bulbs.read.side_effect = slow


async def test_the_ramp_is_fitted_to_a_read_at_the_point_it_had_reached(hass, commands, bulbs, clock):
    """HA shows 60 %, but the bulb was set to 80 % elsewhere. The read 0.1 s into a 3 s soft off sees 77.2 %, which is
    on the ramp from 79.8 % to 0, not its start: the restore puts back 79.8 %."""
    bulb(hass)
    bulbs.levels[IEEE] = 196  # 77.2 %
    read_takes(bulbs, clock, 0.2)  # timed at its middle: 0.1 s in
    start = wall_clock_now()

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await hass.async_block_till_done()
    clock.now -= 0.1  # back to the read's middle, where the ramp passes through what it saw
    assert transition_cache(hass).value("light.bulb", BRIGHTNESS, 0) == pytest.approx(196 * 100 / 254)
    await advance(hass, start, 4.5)

    restore = (0x0008, 0x00, {"level": 203, "transition_time": 0, "options_mask": 1, "options_override": 1})
    assert sent(commands)[-1] == restore


@pytest.mark.parametrize("stopped", [False, True], ids=["read_after_the_fade_ended", "read_after_a_stop"])
async def test_a_read_too_late_to_fit_changes_nothing(hass, commands, bulbs, clock, stopped):
    bulb(hass)
    bulbs.levels[IEEE] = 10
    read_takes(bulbs, clock, 1 if stopped else 10)
    if stopped:
        original = bulbs.read.side_effect

        async def stop_first(*args, **kwargs):
            transition_cache(hass).stopped("light.bulb", BRIGHTNESS, 55.0)
            return await original(*args, **kwargs)

        bulbs.read.side_effect = stop_first

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await hass.async_block_till_done()

    assert transition_cache(hass).value("light.bulb", BRIGHTNESS, -1) == (55.0 if stopped else -1)


async def test_nothing_to_do_by_a_stale_prediction_plans_again_from_has_state(hass, commands):
    """A soft off, then the light turned back on at 100 % from HA within the prediction's window: a lower runs."""
    bulb(hass)
    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    transition_cache(hass).clock.now += 5  # predicted at 0 for 2 s more
    bulb(hass, brightness=255)

    response = await call(hass, "lower_brightness", {"entity_id": "light.bulb"})

    assert response == {"light.bulb": SENT}
    assert sent(commands)[-1] == (0x0008, 0x04, {"level": 0, "transition_time": 50})


async def test_planning_again_keeps_a_running_saturation_fade(hass, commands, clock):
    """Only the stale brightness prediction goes: a stop still halts the saturation fade with StopMoveStep."""
    bulb(hass)
    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    clock.now += 5  # predicted at 0 for 2 s more
    bulb(hass, brightness=255)
    await call(hass, "raise_saturation", {"entity_id": "light.bulb", "sweep_time": 10})

    await call(hass, "lower_brightness", {"entity_id": "light.bulb"})
    await call(hass, "stop", {"entity_id": "light.bulb"})

    assert sent(commands)[-2:] == [(0x0300, 0x47, {"options_mask": 0, "options_override": 0}), (0x0008, 0x03, {})]
