"""Matter turn_on_for: OnWithTimedOff on the OnOff cluster, with OnTime read-back."""

import pytest
from homeassistant.exceptions import HomeAssistantError

from ...conftest import call
from ...fixtures.matter import (
    NODE_ID,
    add_matter_entity,
    matter_device,
)

CONFIRMED = {"status": "confirmed", "integration": "matter"}
EP = 1  # endpoint_id used across tests


@pytest.fixture
def setup_matter(hass, mock_chip, setup_production):
    """Combine the chip mock with a loaded production integration."""
    return hass


async def test_sends_on_with_timed_off_and_confirms(setup_matter, hass):
    """Happy path: command sent, OnTime read-back > 0 -> CONFIRMED."""
    entry, send_cmd, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": CONFIRMED}
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
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": {"seconds": 1, "milliseconds": 500}})

    cmd = send_cmd.call_args.kwargs["command"]
    assert cmd.onTime == 15  # 1.5 s * 10 = 15 tenths


async def test_no_lt_feature_returns_unsupported(setup_matter, hass):
    """An endpoint without the LT feature bit returns no_lt_feature unsupported."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0000)
    add_matter_entity(hass, entry, "light.plug_as_light", endpoint_id=EP)
    # need a second entity that succeeds so the call doesn't raise all_targets_failed
    second_entry, _, _ = matter_device(hass, endpoint_id=2, feature_map=0x0002)
    add_matter_entity(hass, second_entry, "light.real_bulb", endpoint_id=2)

    response = await call(
        hass,
        "turn_on_for",
        {"entity_id": ["light.plug_as_light", "light.real_bulb"], "duration": 5},
    )

    assert response["light.plug_as_light"] == {
        "status": "unsupported",
        "integration": "matter",
        "detail": "no_lt_feature",
    }
    assert response["light.real_bulb"] == CONFIRMED
    send_cmd.assert_not_awaited()


async def test_readback_fails_returns_sent(setup_matter, hass):
    """If read_attribute raises, the result is SENT with readback_failed."""
    entry, send_cmd, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    read_attr.side_effect = ConnectionError("lost connection")
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": {"status": "sent", "integration": "matter", "detail": "readback_failed"}}


async def test_readback_returns_zero_reports_timer_not_running(setup_matter, hass):
    """If read_attribute returns 0 (or falsy), the timer did not start -> timer_not_reported."""
    entry, send_cmd, read_attr = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    read_attr.return_value = 0
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": {"status": "sent", "integration": "matter", "detail": "timer_not_reported"}}


async def test_send_error_rejects_target(setup_matter, hass):
    """If send_device_command raises, the target is REJECTED and all_targets_failed is raised."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    send_cmd.side_effect = ConnectionError("device unreachable")
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert raised.value.translation_key == "all_targets_failed"


async def test_duration_beyond_limit_is_clamped(setup_matter, hass):
    """A duration longer than 6553.4 s is clamped to the limit."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    add_matter_entity(hass, entry, "light.bulb", endpoint_id=EP)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": {"hours": 2}})

    assert response["light.bulb"]["clamped_to"] == 6553.4
    cmd = send_cmd.call_args.kwargs["command"]
    assert cmd.onTime == round(6553.4 * 10)


async def test_not_addressable_when_unique_id_unparseable(setup_matter, hass):
    """An entity whose unique_id doesn't match the expected format returns not_addressable."""
    entry, send_cmd, _ = matter_device(hass, endpoint_id=EP, feature_map=0x0002)
    # Supply an entity whose unique_id has too few parts to parse.
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("matter", "deviceid_bad")},
    )
    er.async_get(hass).async_get_or_create(
        "light", "matter", "bad-uid", suggested_object_id="broken", config_entry=entry, device_id=device.id
    )
    hass.states.async_set("light.broken", "off", {})

    # Need a successful entity alongside to avoid all_targets_failed.
    entry2, _, _ = matter_device(hass, endpoint_id=2, feature_map=0x0002)
    add_matter_entity(hass, entry2, "light.good", endpoint_id=2)

    response = await call(
        hass,
        "turn_on_for",
        {"entity_id": ["light.broken", "light.good"], "duration": 5},
    )

    assert response["light.broken"]["detail"] == "not_addressable"
    assert response["light.good"] == CONFIRMED
