"""Shelly turn_on_for: one <Component>.Set with toggle_after, GetStatus read-back."""

from unittest.mock import call as rpc_call

import pytest
from homeassistant.exceptions import HomeAssistantError

from ...conftest import call
from ...fixtures.shelly import add_shelly_entity, shelly_device

CONFIRMED = {"status": "confirmed", "mode": "native", "platform": "shelly"}


async def test_switch_one_set_then_read_back(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:1")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5})

    assert response == {"switch.porch": CONFIRMED}
    assert call_rpc.await_args_list == [
        rpc_call("Switch.Set", {"id": 1, "on": True, "toggle_after": 5.0}),
        rpc_call("Switch.GetStatus", {"id": 1}),
    ]


async def test_light_fields_ride_in_the_same_set(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "light.desk", "light:0")

    response = await call(
        hass, "turn_on_for", {"entity_id": "light.desk", "duration": 5, "brightness": 128, "transition": 0.2}
    )

    assert response == {"light.desk": CONFIRMED}
    # Translated as shelly/light.py does: brightness to percent, transition floored at 0.5 s.
    assert call_rpc.await_args_list[0] == rpc_call(
        "Light.Set", {"id": 0, "on": True, "toggle_after": 5.0, "brightness": 50, "transition_duration": 0.5}
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"color_temp_kelvin": 9000}, {"ct": 6500, "mode": "cct"}),
        ({"color_temp_kelvin": 1500}, {"ct": 2700, "mode": "cct"}),
        ({"rgb_color": [255, 0, 10]}, {"rgb": [255, 0, 10], "mode": "rgb"}),
    ],
)
async def test_rgbcct_sets_mode_and_clamps_kelvin_to_the_entity_range(hass, setup_production, data, expected):
    entry, call_rpc = shelly_device(hass)
    kelvin_range = {"min_color_temp_kelvin": 2700, "max_color_temp_kelvin": 6500}
    add_shelly_entity(hass, entry, "light.strip", "rgbcct:0", attributes=kelvin_range)

    await call(hass, "turn_on_for", {"entity_id": "light.strip", "duration": 5, **data})

    assert call_rpc.await_args_list[0] == rpc_call("RGBCCT.Set", {"id": 0, "on": True, "toggle_after": 5.0, **expected})


async def test_switch_ignores_light_fields(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5, "brightness": 10})

    assert response == {"switch.porch": {**CONFIRMED, "detail": "light_fields_ignored"}}
    assert call_rpc.await_args_list[0] == rpc_call("Switch.Set", {"id": 0, "on": True, "toggle_after": 5.0})


@pytest.mark.parametrize(
    ("entity_id", "key", "data"),
    [
        ("light.relay", "switch:0", {"brightness": 10}),  # a relay shown as a light is on/off only
        ("light.dimmer", "light:0", {"color_temp_kelvin": 3000}),
        ("light.cct", "cct:0", {"rgb_color": [1, 2, 3]}),
        ("light.rgb", "rgb:0", {"hs_color": [30, 50]}),  # not claimed on any component
    ],
)
async def test_fields_the_component_cannot_take_are_refused(hass, setup_production, entity_id, key, data):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, entity_id, key)
    add_shelly_entity(hass, entry, "switch.porch", "switch:1")

    response = await call(hass, "turn_on_for", {"entity_id": [entity_id, "switch.porch"], "duration": 5, **data})

    assert response[entity_id] == {
        "status": "unsupported",
        "mode": "native",
        "platform": "shelly",
        "detail": "fields_not_supported",
    }
    assert [args.args[0] for args in call_rpc.await_args_list] == ["Switch.Set", "Switch.GetStatus"]


async def test_gen1_and_non_timer_entities_are_unsupported(hass, setup_production):
    gen1, _ = shelly_device(hass, gen1=True, mac="112233445566")
    add_shelly_entity(hass, gen1, "switch.old_relay", "relay_0")
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.child_lock", "boolean:200-boolean_child_lock")
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(
        hass, "turn_on_for", {"entity_id": ["switch.child_lock", "switch.old_relay", "switch.porch"], "duration": 5}
    )

    assert response["switch.old_relay"]["detail"] == "gen1_unsupported"
    assert response["switch.child_lock"]["detail"] == "not_addressable"
    assert response["switch.porch"] == CONFIRMED


async def test_set_error_rejects_only_that_target(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    call_rpc.side_effect = ConnectionError("device unreachable")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5})

    assert raised.value.translation_key == "all_targets_failed"
    assert raised.value.translation_placeholders == {"summary": "switch.porch: error"}


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (ConnectionError("gone"), "readback_failed"),
        ({"id": 0, "output": True}, "timer_not_reported"),  # timer fields absent
        ({"id": 0, "output": False, "timer_duration": 5.0}, "timer_not_reported"),  # output not what we sent
    ],
)
async def test_inconclusive_read_back_reports_sent(hass, setup_production, status, detail):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    call_rpc.side_effect = [{"was_on": False}, status]

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5})

    assert response == {"switch.porch": {"status": "sent", "mode": "native", "platform": "shelly", "detail": detail}}


async def test_duration_beyond_the_limit_is_clamped(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": {"days": 2}})

    assert response == {"switch.porch": {**CONFIRMED, "clamped_to": 86400}}
    assert call_rpc.await_args_list[0].args[1]["toggle_after"] == 86400
