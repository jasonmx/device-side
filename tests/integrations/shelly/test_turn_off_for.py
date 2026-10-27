"""Shelly turn_off_for: the turn_on_for Set with on=False; the device flips itself back on."""

from unittest.mock import call as rpc_call

from ...conftest import call, refusal
from ...fixtures.shelly import add_shelly_entity, shelly_device

CONFIRMED = {"status": "confirmed", "integration": "shelly"}


async def test_each_capability_in_scope_gets_a_set(hass, setup_production):
    entry, call_rpc = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.heater", "switch:0", state="on")
    add_shelly_entity(hass, entry, "light.lamp", "switch:1", state="on")
    add_shelly_entity(hass, entry, "light.bulb", "rgbcct:2", state="on")

    response = await call(
        hass,
        "turn_off_for",
        {"entity_id": ["light.lamp", "light.bulb", "switch.heater"], "duration": 90},
    )

    assert response == {
        "light.lamp": CONFIRMED,
        "light.bulb": CONFIRMED,
        "switch.heater": CONFIRMED,
    }
    sets = [args for args in call_rpc.await_args_list if args.args[0].endswith(".Set")]
    assert sorted(sets, key=lambda args: args.args[1]["id"]) == [
        rpc_call("Switch.Set", {"id": 0, "on": False, "toggle_after": 90.0}),
        rpc_call("Switch.Set", {"id": 1, "on": False, "toggle_after": 90.0}),
        rpc_call("RGBCCT.Set", {"id": 2, "on": False, "toggle_after": 90.0}),
    ]


async def test_rgbw_is_refused(hass, setup_production):
    entry, _ = shelly_device(hass)
    add_shelly_entity(hass, entry, "light.strip", "rgbw:0", state="on")

    assert await refusal(hass, "turn_off_for", {"entity_id": "light.strip", "duration": 90}) == "capability_not_tested"


async def test_gen1_is_refused(hass, setup_production):
    gen1, _ = shelly_device(hass, gen1=True, mac="112233445566")
    add_shelly_entity(hass, gen1, "switch.old_relay", "relay_0")
    entry, _ = shelly_device(hass)
    add_shelly_entity(hass, entry, "switch.heater", "switch:0")

    assert await refusal(hass, "turn_off_for", {"entity_id": "switch.old_relay", "duration": 5}) == "gen1_unsupported"
    assert await call(hass, "turn_off_for", {"entity_id": "switch.heater", "duration": 5}) == {
        "switch.heater": CONFIRMED
    }
