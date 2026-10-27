"""Shelly get_attributes: one GetStatus per target, shaped as Hue's row plus the shared timer row."""

from datetime import UTC, datetime, timedelta
from unittest.mock import call as rpc_call

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.color import color_RGB_to_hs, color_RGB_to_xy

from custom_components.device_side.integrations.shelly.get_attributes import status_row

from ...conftest import call, refusal
from ...fixtures.fake import add_switch_as_x
from ...fixtures.shelly import TIMER_STARTED_AT, add_shelly_entity, shelly_device

pytestmark = pytest.mark.usefixtures("setup_production")

# Two seconds into a fixture timer.
NOW = datetime.fromtimestamp(TIMER_STARTED_AT, UTC) + timedelta(seconds=2)
BULB = {"brightness": 40, "ct": 4000, "rgb": [255, 0, 0]}


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(dt_util, "utcnow", lambda: NOW)


def timer(turns: str, remaining_s: float) -> dict:
    ends_at = (NOW + timedelta(seconds=remaining_s)).isoformat()
    return {"turns": turns, "ends_at": ends_at, "remaining_s": remaining_s}


@pytest.mark.parametrize(("action", "turns"), [("turn_on_for", "off"), ("turn_off_for", "on")])
async def test_switch_reports_the_running_timer(hass, action, turns):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:1")
    await call(hass, action, {"entity_id": "switch.porch", "duration": 5})

    response = await call(hass, "get_attributes", {"entity_id": "switch.porch"})

    assert response == {"switch.porch": {"timer": timer(turns, 3.0)}}
    assert call_rpc.await_args_list[-1] == rpc_call("Switch.GetStatus", {"id": 1})


async def test_switch_as_x_light_reads_the_switch(hass):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    add_switch_as_x(hass, "light.porch", "switch.porch")
    await call(hass, "turn_on_for", {"entity_id": "light.porch", "duration": 5})

    response = await call(hass, "get_attributes", {"entity_id": "light.porch"})

    assert response == {"light.porch": {"timer": timer("off", 3.0)}}
    assert call_rpc.await_args_list[-1] == rpc_call("Switch.GetStatus", {"id": 0})


async def test_switch_without_a_timer_reports_an_empty_row(hass):
    entry, _ = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    assert await call(hass, "get_attributes", {"entity_id": "switch.porch"}) == {"switch.porch": {}}


async def test_bulb_in_cct_mode_reports_color_temperature_only(hass):
    entry, _ = shelly_device(hass, status={**BULB, "output": True, "mode": "cct"})
    add_shelly_entity(hass, entry, "light.bulb", "rgbcct:0", state="on")

    response = await call(hass, "get_attributes", {"entity_id": "light.bulb"})

    assert response == {"light.bulb": {"brightness": 40, "color_temp_kelvin": 4000}}


async def test_bulb_in_rgb_mode_reports_color_as_hue_does(hass):
    entry, _ = shelly_device(hass, status={**BULB, "output": True, "mode": "rgb"})
    add_shelly_entity(hass, entry, "light.bulb", "rgbcct:0", state="on")

    response = await call(hass, "get_attributes", {"entity_id": "light.bulb"})

    assert response == {
        "light.bulb": {
            "brightness": 40,
            "rgb_color": [255, 0, 0],
            "hs_color": list(color_RGB_to_hs(255, 0, 0)),
            "xy_color": list(color_RGB_to_xy(255, 0, 0)),
        }
    }


async def test_bulb_off_still_reads_and_carries_its_timer(hass):
    # The bulb keeps brightness, ct and rgb in its status while off (probed on a Multicolor Bulb Gen3).
    entry, _ = shelly_device(hass, status={**BULB, "mode": "cct"})
    add_shelly_entity(hass, entry, "light.bulb", "rgbcct:0")
    await call(hass, "turn_off_for", {"entity_id": "light.bulb", "duration": 30})

    response = await call(hass, "get_attributes", {"entity_id": "light.bulb"})

    assert response == {"light.bulb": {"brightness": 40, "color_temp_kelvin": 4000, "timer": timer("on", 28.0)}}


@pytest.mark.parametrize(
    ("started_at", "remaining_s"),
    [
        (TIMER_STARTED_AT + 10, 5.0),  # device clock ahead of HA's: never more than the duration
        (TIMER_STARTED_AT - 10, 0.0),  # timer overdue: never negative
    ],
)
def test_remaining_time_is_clamped_to_the_duration(started_at, remaining_s):
    status = {"output": True, "timer_started_at": started_at, "timer_duration": 5.0}

    assert status_row("Switch", status, NOW) == {"timer": timer("off", remaining_s)}


async def test_gen1_and_non_timer_entities_are_refused(hass):
    gen1, _ = shelly_device(hass, gen1=True, mac="112233445566")
    add_shelly_entity(hass, gen1, "switch.old_relay", "relay_0")
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.child_lock", "boolean:200-boolean_child_lock")

    assert await refusal(hass, "get_attributes", {"entity_id": "switch.old_relay"}) == "gen1_unsupported"
    assert await refusal(hass, "get_attributes", {"entity_id": "switch.child_lock"}) == "not_addressable"
    assert not call_rpc.await_args_list


@pytest.mark.parametrize("key", ["light:0", "cct:0", "rgb:0", "rgbw:0"])
async def test_untested_light_components_are_refused(hass, key):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "light.lamp", key)

    assert await refusal(hass, "get_attributes", {"entity_id": "light.lamp"}) == "capability_not_tested"
    assert not call_rpc.await_args_list


async def test_get_status_error_raises(hass):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    call_rpc.side_effect = ConnectionError("device unreachable")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_attributes", {"entity_id": "switch.porch"})

    assert raised.value.translation_key == "targets_failed"
    assert raised.value.translation_placeholders == {"summary": "switch.porch: error"}


async def test_mixed_targets_read_in_one_call(hass):
    entry, call_rpc = shelly_device(hass, status={**BULB, "mode": "cct"})
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    add_shelly_entity(hass, entry, "light.bulb", "rgbcct:0")
    await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5})

    response = await call(hass, "get_attributes", {"entity_id": ["switch.porch", "light.bulb"]})

    assert response == {
        "switch.porch": {"timer": timer("off", 3.0)},  # a Switch reads only its timer from the shared status
        "light.bulb": {"brightness": 40, "color_temp_kelvin": 4000},
    }
