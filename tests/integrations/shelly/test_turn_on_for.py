"""Shelly turn_on_for: one <Component>.Set with toggle_after, GetStatus read-back."""

import dataclasses
from unittest.mock import call as rpc_call

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.device_side.integrations.shelly.turn_on_for import ShellyTurnOnFor

from ...conftest import call
from ...fixtures.fake import add_switch_as_x
from ...fixtures.shelly import add_shelly_entity, shelly_device

CONFIRMED = {"status": "confirmed", "integration": "shelly"}


@pytest.fixture
def every_light_in_scope(monkeypatch):
    """Light fields and capabilities as testers' reports would add them; until then they are refused first."""
    fields = frozenset({"brightness", "transition", "color_temp_kelvin", "rgb_color"})
    scope = dataclasses.replace(ShellyTurnOnFor.scope, fields=fields, capabilities=None)
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
async def test_rgbcct_sets_mode_and_clamps_kelvin_to_the_entity_range(
    hass, setup_production, every_light_in_scope, data, expected
):
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


async def test_switch_as_x_light_sends_the_switch_call(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.porch", "switch:0")
    add_switch_as_x(hass, "light.porch", "switch.porch")

    response = await call(hass, "turn_on_for", {"entity_id": "light.porch", "duration": 5})

    assert response == {"light.porch": CONFIRMED}
    assert call_rpc.await_args_list[0] == rpc_call("Switch.Set", {"id": 0, "on": True, "toggle_after": 5.0})


@pytest.mark.parametrize(
    ("entity_id", "key", "data", "detail"),
    [
        ("light.relay", "switch:0", {"brightness": 10}, "fields_not_supported"),  # a relay shown as a light is on/off
        ("light.dimmer", "light:0", {"color_temp_kelvin": 3000}, "fields_not_supported"),
        ("light.cct", "cct:0", {"rgb_color": [1, 2, 3]}, "fields_not_supported"),
        ("light.rgb", "rgb:0", {"hs_color": [30, 50]}, "fields_not_tested"),  # in no component's scope
    ],
)
async def test_fields_outside_the_component_or_scope_are_refused(
    hass, setup_production, every_light_in_scope, entity_id, key, data, detail
):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, entity_id, key)
    add_shelly_entity(hass, entry, "switch.porch", "switch:1")

    response = await call(hass, "turn_on_for", {"entity_id": [entity_id, "switch.porch"], "duration": 5, **data})

    assert response[entity_id] == {
        "status": "unsupported",
        "integration": "shelly",
        "detail": detail,
    }
    assert [args.args[0] for args in call_rpc.await_args_list] == ["Switch.Set", "Switch.GetStatus"]


async def test_relay_lights_run_but_fields_and_capabilities_out_of_scope_are_refused(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "light.dimmer", "light:0")
    add_shelly_entity(hass, entry, "light.relay", "switch:0")

    with pytest.raises(HomeAssistantError, match="light.relay: fields_not_tested"):
        await call(hass, "turn_on_for", {"entity_id": "light.relay", "duration": 5, "brightness": 10})
    response = await call(hass, "turn_on_for", {"entity_id": ["light.dimmer", "light.relay"], "duration": 5})

    assert response["light.relay"] == CONFIRMED
    assert response["light.dimmer"] == {**CONFIRMED, "status": "unsupported", "detail": "capability_not_tested"}
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
