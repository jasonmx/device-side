"""Shelly turn_on_for against the house: the device's own toggle_after turns it back off."""

import asyncio

import pytest

from .client import HAClient, HAError

ROLES = ["switch_plug", "light_dimmable"]
RIG_SECONDS = 25

DURATION_S = 6


def is_on(state: dict | None) -> bool:
    return state is not None and state["state"] == "on"


def is_off(state: dict | None) -> bool:
    return state is not None and state["state"] == "off"


async def test_switch_on_then_off_after_duration(ha: HAClient, snapshot, require_cell, timing):
    entity_id = require_cell("shelly", "turn_on_for", "switch_plug")
    tolerance = timing("shelly")
    await snapshot.take(entity_id)
    await ha.call_service("switch", "turn_off", {"entity_id": entity_id})
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


async def test_unsupported_color_on_dimmable_light_raises(ha: HAClient, snapshot, require_cell):
    entity_id = require_cell("shelly", "turn_on_for", "light_dimmable")
    before = await snapshot.take(entity_id)

    with pytest.raises(HAError) as err:
        await ha.call_service(
            "device_side",
            "turn_on_for",
            {"entity_id": entity_id, "duration": {"seconds": DURATION_S}, "hs_color": [120, 100]},
            return_response=True,
        )

    assert err.value.translation_key == "all_targets_failed", err.value
    assert (await ha.get_state(entity_id))["state"] == before["state"]
