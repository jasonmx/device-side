"""Shelly turn_on_for against the house: the device's own toggle_after turns it back off.

A relay sends the same Switch.Set whether HA shows it as a switch or a light, so the happy path runs on
whichever the inventory has; a pass on either proves on/off for both.
"""

import asyncio

import pytest

from .client import HAClient, HAError

ROLES = ["switch_plug", "light_onoff"]
RIG_SECONDS = 25

DURATION_S = 6


def is_on(state: dict | None) -> bool:
    return state is not None and state["state"] == "on"


def is_off(state: dict | None) -> bool:
    return state is not None and state["state"] == "off"


@pytest.mark.parametrize("role", ROLES)
async def test_on_then_off_after_duration(ha: HAClient, snapshot, require_adapter, timing, role):
    entity_id = require_adapter("shelly", "turn_on_for", role)
    domain = entity_id.partition(".")[0]
    tolerance = timing("shelly")
    await snapshot.take(entity_id)
    await ha.call_service(domain, "turn_off", {"entity_id": entity_id})
    await ha.wait_for(entity_id, is_off, tolerance)

    data = {"entity_id": entity_id, "duration": {"seconds": DURATION_S}}
    response = await ha.call_service("device_side", "turn_on_for", data, return_response=True)

    assert response[entity_id]["status"] in ("confirmed", "sent"), response
    assert response[entity_id]["platform"] == "shelly"
    assert response[entity_id]["mode"] == "native"
    await ha.wait_for(entity_id, is_on, tolerance)
    await asyncio.sleep(DURATION_S - tolerance)
    assert is_on(await ha.get_state(entity_id)), "turned off before the duration"
    await ha.wait_for(entity_id, is_off, 2 * tolerance)


async def test_unclaimed_brightness_on_a_light_raises(ha: HAClient, snapshot, require_adapter):
    entity_id = require_adapter("shelly", "turn_on_for", "light_onoff")
    before = await snapshot.take(entity_id)

    with pytest.raises(HAError) as err:
        await ha.call_service(
            "device_side",
            "turn_on_for",
            {"entity_id": entity_id, "duration": {"seconds": DURATION_S}, "brightness": 128},
            return_response=True,
        )

    assert err.value.translation_key == "all_targets_failed", err.value
    assert (await ha.get_state(entity_id))["state"] == before["state"]
