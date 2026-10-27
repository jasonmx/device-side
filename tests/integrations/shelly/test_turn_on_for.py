"""Shelly turn_on_for: one <Component>.Set with toggle_after, GetStatus read-back."""

import dataclasses
from unittest.mock import call as rpc_call

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.device_side.integrations.shelly.turn_on_for import ShellyTurnOnFor

from ...conftest import call, refusal
from ...fixtures.fake import add_switch_as_x
from ...fixtures.shelly import add_shelly_entity, shelly_device

CONFIRMED = {"status": "confirmed", "integration": "shelly"}


@pytest.fixture
def every_light_in_scope(monkeypatch):
    """Light, CCT, RGB and RGBW as testers' reports would add them; until then they are refused first."""
    scope = dataclasses.replace(ShellyTurnOnFor.scope, capabilities=None)
    monkeypatch.setattr(ShellyTurnOnFor, "scope", scope)


async def test_switch_one_set_then_read_back(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:1")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5})

    assert response == {"switch.porch": CONFIRMED}
    assert call_rpc.await_args_list == [
        rpc_call("Switch.Set", {"id": 1, "on": True, "toggle_after": 5.0}),
        rpc_call("Switch.GetStatus", {"id": 1}),
    ]


async def test_light_fields_ride_in_the_same_set(hass, setup_production, every_light_in_scope):
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
    add_shelly_entity(hass, entry, "light.bulb", "rgbcct:0", attributes=kelvin_range)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5, **data})

    assert response == {"light.bulb": CONFIRMED}
    assert call_rpc.await_args_list[0] == rpc_call("RGBCCT.Set", {"id": 0, "on": True, "toggle_after": 5.0, **expected})


async def test_switch_drops_light_fields(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5, "brightness": 10})

    # The dispatcher drops brightness for a switch domain; the timer still runs.
    assert response == {"switch.porch": {**CONFIRMED, "detail": "fields_dropped"}}
    assert call_rpc.await_args_list[0] == rpc_call("Switch.Set", {"id": 0, "on": True, "toggle_after": 5.0})


async def test_switch_as_x_light_sends_the_switch_call(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    add_switch_as_x(hass, "light.porch", "switch.porch")

    response = await call(hass, "turn_on_for", {"entity_id": "light.porch", "duration": 5})

    assert response == {"light.porch": CONFIRMED}
    assert call_rpc.await_args_list[0] == rpc_call("Switch.Set", {"id": 0, "on": True, "toggle_after": 5.0})


@pytest.mark.parametrize(
    ("entity_id", "key", "data"),
    [
        ("light.relay", "switch:0", {"brightness": 10}),   # relay shown as a light is on/off
        ("light.dimmer", "light:0", {"color_temp_kelvin": 3000}),
        ("light.cct", "cct:0", {"rgb_color": [1, 2, 3]}),
    ],
)
async def test_component_fields_not_in_component_are_dropped(
    hass, setup_production, every_light_in_scope, entity_id, key, data
):
    # A field the component can't take is dropped by the adapter; the timer still runs.
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, entity_id, key)

    response = await call(hass, "turn_on_for", {"entity_id": entity_id, "duration": 5, **data})

    assert response[entity_id] == {**CONFIRMED, "detail": "fields_dropped"}


async def test_field_not_in_scope_is_refused(hass, setup_production, every_light_in_scope):
    # A field not in scope is refused before anything is sent.
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "light.rgb", "rgb:0")

    data = {"entity_id": "light.rgb", "duration": 5, "hs_color": [30, 50]}
    assert await refusal(hass, "turn_on_for", data) == "fields_not_tested"
    assert not call_rpc.await_args_list


async def test_relay_drops_brightness_and_dimmer_is_refused_by_capability(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "light.relay", "switch:0")
    add_shelly_entity(hass, entry, "light.dimmer", "light:0")

    # A relay-as-light drops brightness it can't take and still runs the timer.
    response = await call(hass, "turn_on_for", {"entity_id": "light.relay", "duration": 5, "brightness": 10})
    assert response["light.relay"] == {**CONFIRMED, "detail": "fields_dropped"}

    # An untested capability (Light:0) raises before any new sends.
    assert await refusal(hass, "turn_on_for", {"entity_id": "light.dimmer", "duration": 5}) == "capability_not_tested"
    assert [args.args[0] for args in call_rpc.await_args_list] == ["Switch.Set", "Switch.GetStatus"]


async def test_gen1_and_non_timer_entities_are_refused(hass, setup_production):
    gen1, _ = shelly_device(hass, gen1=True, mac="112233445566")
    add_shelly_entity(hass, gen1, "switch.old_relay", "relay_0")
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.child_lock", "boolean:200-boolean_child_lock")
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.old_relay", "duration": 5}) == "gen1_unsupported"
    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.child_lock", "duration": 5}) == "not_addressable"
    assert await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5}) == {"switch.porch": CONFIRMED}


async def test_set_error_rejects_only_that_target(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    call_rpc.side_effect = ConnectionError("device unreachable")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": 5})

    assert raised.value.translation_key == "targets_failed"
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

    assert response == {"switch.porch": {"status": "sent", "integration": "shelly", "detail": detail}}


async def test_duration_beyond_the_limit_is_clamped(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": {"days": 8}})

    assert response == {"switch.porch": {**CONFIRMED, "clamped_to": 604800}}
    assert call_rpc.await_args_list[0].args[1]["toggle_after"] == 604800


async def test_fractional_duration_passes_through_unrounded(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": {"milliseconds": 50}})

    assert response == {"switch.porch": CONFIRMED}
    assert call_rpc.await_args_list[0].args[1]["toggle_after"] == 0.05


async def test_duration_under_50ms_is_floored_and_reported(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")

    response = await call(hass, "turn_on_for", {"entity_id": "switch.porch", "duration": {"milliseconds": 20}})

    assert response == {"switch.porch": {**CONFIRMED, "clamped_to": 0.05}}
    assert call_rpc.await_args_list[0].args[1]["toggle_after"] == 0.05
