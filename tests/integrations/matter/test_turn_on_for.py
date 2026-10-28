"""Matter turn_on_for: OnWithTimedOff on the OnOff cluster, with OnTime read-back."""

import pytest
from homeassistant.exceptions import HomeAssistantError

from ...conftest import call, refusal
from ...fixtures.matter import (
    NODE_ID,
    add_matter_entity,
    matter_device,
    on_time_reads,
)

CONFIRMED = {"status": "confirmed", "integration": "matter"}
EP = 1  # endpoint_id used across tests


@pytest.fixture
def setup_matter(hass, mock_chip, setup_production):
    """Combine the chip mock with a loaded production integration."""
    return hass


async def test_sends_on_with_timed_off_and_confirms(setup_matter, hass):
    """Happy path: command sent, OnTime read-back > 0 -> CONFIRMED."""
    entry, send_cmd, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": 5})

    assert response == {"switch.bulb": CONFIRMED}
    send_cmd.assert_awaited_once()
    call_kwargs = send_cmd.call_args.kwargs
    assert call_kwargs["node_id"] == NODE_ID
    assert call_kwargs["endpoint_id"] == EP
    cmd = call_kwargs["command"]
    assert cmd.onOffControl == 0
    assert cmd.onTime == 50  # 5 s * 10 = 50 tenths
    assert cmd.offWaitTime == 0
    read_attr.assert_awaited_once()


async def test_duration_converted_to_tenths(setup_matter, hass):
    """Duration in seconds is multiplied by 10 and rounded to integer tenths."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": {"seconds": 1, "milliseconds": 500}})

    cmd = send_cmd.call_args.kwargs["command"]
    assert cmd.onTime == 15  # 1.5 s * 10 = 15 tenths


async def test_no_lt_feature_is_refused(setup_matter, hass):
    """An endpoint without the LT feature bit raises TargetNotSupported."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0000)
    add_matter_entity(hass, entry, "switch.no_lt", endpoint_id=EP)

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.no_lt", "duration": 5}) == "no_lt_feature"
    send_cmd.assert_not_awaited()


async def test_plug_sends_on_with_timed_off(setup_matter, hass):
    """A plug (switch domain) with the LT bit takes OnWithTimedOff."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    add_matter_entity(hass, entry, "switch.plug", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "switch.plug", "duration": 5})

    assert response == {"switch.plug": CONFIRMED}
    assert send_cmd.call_args.kwargs["command"].onTime == 50


async def test_light_is_out_of_scope(setup_matter, hass):
    """A Matter light raises TargetNotSupported until a tester's report brings lights into scope."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP)
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    assert await refusal(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5}) == "domain_not_tested"


def _no_client(entry):
    del entry.runtime_data


def _node_lookup_raises(entry):
    entry.runtime_data.adapter.matter_client.get_node.side_effect = KeyError("node gone")


def _node_missing(entry):
    entry.runtime_data.adapter.matter_client.get_node.return_value = None


@pytest.mark.parametrize("break_node", [_no_client, _node_lookup_raises, _node_missing])
async def test_unreachable_node_is_refused(setup_matter, hass, break_node):
    """No Matter client, a node lookup that raises, or no node: raises TargetNotSupported."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP)
    break_node(entry)
    add_matter_entity(hass, entry, "switch.gone", endpoint_id=EP)

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.gone", "duration": 5}) == "not_addressable"
    send_cmd.assert_not_awaited()


async def test_dead_front_bit_alone_is_not_lt(setup_matter, hass):
    """FeatureMap 0x2 is DeadFrontBehavior, not Lighting: raises TargetNotSupported."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    add_matter_entity(hass, entry, "switch.dead_front", endpoint_id=EP)

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.dead_front", "duration": 5}) == "no_lt_feature"
    send_cmd.assert_not_awaited()


async def test_featuremap_missing_from_cache_is_not_lt(setup_matter, hass):
    """An endpoint whose OnOff FeatureMap the node never reported raises TargetNotSupported."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP)
    entry.runtime_data.adapter.matter_client.get_node.return_value.node_data.attributes = {}
    add_matter_entity(hass, entry, "switch.unreported", endpoint_id=EP)

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.unreported", "duration": 5}) == "no_lt_feature"
    send_cmd.assert_not_awaited()


async def test_readback_without_the_path_reports_timer_not_running(setup_matter, hass):
    """A read that leaves out the OnTime path does not confirm."""
    entry, _, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    read_attr.side_effect = None
    read_attr.return_value = {}
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": 5})

    assert response == {"switch.bulb": {"status": "sent", "integration": "matter", "detail": "timer_not_reported"}}


async def test_readback_fails_returns_sent(setup_matter, hass):
    """If read_attribute raises, the result is SENT with readback_failed."""
    entry, send_cmd, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    read_attr.side_effect = ConnectionError("lost connection")
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": 5})

    assert response == {"switch.bulb": {"status": "sent", "integration": "matter", "detail": "readback_failed"}}


async def test_readback_returns_zero_reports_timer_not_running(setup_matter, hass):
    """If read_attribute returns 0 (or falsy), the timer did not start -> timer_not_reported."""
    entry, send_cmd, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    read_attr.side_effect = on_time_reads(0).side_effect
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": 5})

    assert response == {"switch.bulb": {"status": "sent", "integration": "matter", "detail": "timer_not_reported"}}


async def test_send_error_rejects_target(setup_matter, hass):
    """If send_device_command raises, the target is REJECTED and targets_failed is raised."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    send_cmd.side_effect = ConnectionError("device unreachable")
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": 5})

    assert raised.value.translation_key == "targets_failed"


async def test_duration_beyond_limit_is_clamped(setup_matter, hass):
    """A duration longer than 6553.4 s is clamped to the limit."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    add_matter_entity(hass, entry, "switch.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "switch.bulb", "duration": {"hours": 2}})

    assert response["switch.bulb"]["clamped_to"] == 6553.4
    cmd = send_cmd.call_args.kwargs["command"]
    assert cmd.onTime == round(6553.4 * 10)


async def test_not_addressable_when_unique_id_unparseable(setup_matter, hass):
    """An entity whose unique_id doesn't match the expected format returns not_addressable."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0001)
    add_matter_entity(hass, entry, "switch.broken", unique_id="bad-uid")

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.broken", "duration": 5}) == "not_addressable"
