"""Shelly turn_off_for: the turn_on_for Set with on=False; the device flips itself back on."""

from unittest.mock import call as rpc_call

from ...conftest import call
from ...fixtures.shelly import add_shelly_entity, shelly_device

CONFIRMED = {"status": "confirmed", "mode": "native", "platform": "shelly"}


async def test_switch_and_relay_light_each_get_one_set_and_an_unclaimed_component_is_refused(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.heater", "switch:0", state="on")
    add_shelly_entity(hass, entry, "light.lamp", "switch:1", state="on")
    add_shelly_entity(hass, entry, "light.strip", "rgbw:0", state="on")

    response = await call(
        hass, "turn_off_for", {"entity_id": ["light.strip", "light.lamp", "switch.heater"], "duration": 90}
    )

    assert response == {
        "light.lamp": CONFIRMED,
        "switch.heater": CONFIRMED,
        "light.strip": {**CONFIRMED, "status": "unsupported", "detail": "component_not_supported"},
    }
    sets = [args for args in call_rpc.await_args_list if args.args[0].endswith(".Set")]
    assert sorted(sets, key=lambda args: args.args[1]["id"]) == [
        rpc_call("Switch.Set", {"id": 0, "on": False, "toggle_after": 90.0}),
        rpc_call("Switch.Set", {"id": 1, "on": False, "toggle_after": 90.0}),
    ]


async def test_gen1_is_unsupported(hass, setup_production):
    gen1, _ = shelly_device(hass, gen1=True, mac="112233445566")
    add_shelly_entity(hass, gen1, "switch.old_relay", "relay_0")
    entry, _ = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.heater", "switch:0")

    response = await call(hass, "turn_off_for", {"entity_id": ["switch.heater", "switch.old_relay"], "duration": 5})

    assert response["switch.old_relay"] == {
        "status": "unsupported",
        "mode": "native",
        "platform": "shelly",
        "detail": "gen1_unsupported",
    }
    assert response["switch.heater"] == CONFIRMED
