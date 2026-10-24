"""Shelly turn_off_for against the house: the device's own toggle_after turns it back on.

Same relay-call argument as turn_on_for: a pass on any role proves on/off for all three.
"""

import asyncio

import pytest

from .client import HAClient, HAError
from .test_shelly_turn_on_for import DURATION_S, is_off, is_on

ROLES = ["switch_plug", "light_onoff", "light_wrapped", "light_dimmable"]
ON_OFF = ROLES[:3]
RIG_SECONDS = 35


@pytest.mark.parametrize("role", ON_OFF)
async def test_off_then_on_after_duration(ha: HAClient, snapshot, require_adapter, timing, role):
    entity_id = require_adapter("shelly", "turn_off_for", role)
    domain = entity_id.partition(".")[0]
    tolerance = timing("shelly")
    await snapshot.take(entity_id)
    await ha.call_service(domain, "turn_on", {"entity_id": entity_id})
    await ha.wait_for(entity_id, is_on, tolerance)

    data = {"entity_id": entity_id, "duration": {"seconds": DURATION_S}}
    response = await ha.call_service("device_side", "turn_off_for", data, return_response=True)

    assert response[entity_id]["status"] in ("confirmed", "sent"), response
    assert response[entity_id]["integration"] == "shelly"
    await ha.wait_for(entity_id, is_off, tolerance)
    await asyncio.sleep(DURATION_S - tolerance)
    assert is_off(await ha.get_state(entity_id)), "turned back on before the duration"
    await ha.wait_for(entity_id, is_on, 2 * tolerance)


async def test_dimmer_out_of_scope_is_refused(ha: HAClient, snapshot, require_adapter):
    entity_id = require_adapter("shelly", "turn_off_for", "light_dimmable")
    before = await snapshot.take(entity_id)

    with pytest.raises(HAError) as err:
        data = {"entity_id": entity_id, "duration": {"seconds": DURATION_S}}
        await ha.call_service("device_side", "turn_off_for", data, return_response=True)

    assert err.value.translation_placeholders["summary"] == f"{entity_id}: capability_not_tested", err.value
    assert (await ha.get_state(entity_id))["state"] == before["state"]
