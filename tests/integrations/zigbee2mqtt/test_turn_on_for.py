"""Zigbee2MQTT turn_on_for: optional light.turn_on then mqtt.publish with on_time."""

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.device_side.integrations.zigbee2mqtt.addressing import (
    is_z2m_group,
    topic,
    z2m_address,
)
from custom_components.device_side.integrations.zigbee2mqtt.detect import detect

from ...conftest import call
from ...fixtures.z2m import IEEE, add_z2m_entity, add_z2m_group, z2m_entry

SENT = {"status": "sent", "integration": "zigbee2mqtt"}
TOPIC = f"zigbee2mqtt/{IEEE}/set"
GET_TOPIC = f"zigbee2mqtt/{IEEE}/get"


@pytest.fixture
def publishes(hass):
    return async_mock_service(hass, "mqtt", "publish")


@pytest.fixture
def turn_ons(hass):
    return async_mock_service(hass, "light", "turn_on")


async def test_light_without_fields_publishes_on_time(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")

    response = await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 5})

    assert response == {"light.kitchen": SENT}
    assert not turn_ons
    assert len(publishes) == 1
    assert publishes[0].data["topic"] == TOPIC
    assert json.loads(publishes[0].data["payload"]) == {"state": "ON", "on_time": 5.0}


async def test_light_with_brightness_calls_turn_on_then_publishes_on_time(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")

    response = await call(
        hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 10, "brightness": 128}
    )

    assert response == {"light.kitchen": SENT}
    assert len(turn_ons) == 1
    assert turn_ons[0].data == {"entity_id": "light.kitchen", "brightness": 128}
    assert len(publishes) == 1
    assert publishes[0].data["topic"] == TOPIC
    assert json.loads(publishes[0].data["payload"]) == {"state": "ON", "on_time": 10.0}


async def test_light_with_multiple_fields_passes_them_all_to_turn_on(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")

    await call(
        hass,
        "turn_on_for",
        {"entity_id": "light.kitchen", "duration": 5, "brightness": 200, "color_temp_kelvin": 3000},
    )

    assert len(turn_ons) == 1
    assert turn_ons[0].data == {"entity_id": "light.kitchen", "brightness": 200, "color_temp_kelvin": 3000}
    assert len(publishes) == 1


async def test_switch_is_out_of_scope(hass, setup_production, publishes, turn_ons):
    add_z2m_entity(hass, z2m_entry(hass), "switch.plug")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "switch.plug", "duration": 5})

    assert raised.value.translation_placeholders["summary"] == "switch.plug: domain_not_tested"
    assert not publishes


async def test_duration_rounded_to_one_decimal_place(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")

    await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": {"milliseconds": 1500}})

    assert json.loads(publishes[0].data["payload"]) == {"state": "ON", "on_time": 1.5}


async def test_duration_clamped_to_z2m_max(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")

    response = await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": {"hours": 2}})

    assert response == {"light.kitchen": {**SENT, "clamped_to": 6553.4}}
    assert json.loads(publishes[0].data["payload"]) == {"state": "ON", "on_time": 6553.4}


async def test_non_z2m_mqtt_entity_is_unsupported(hass, setup_production, publishes, turn_ons):
    """An MQTT entity whose device lacks the zigbee2mqtt_ identifier is not detected as Z2M."""
    entry = z2m_entry(hass)
    other_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("mqtt", "some_other_bridge_0x1234")},
    )
    er.async_get(hass).async_get_or_create(
        "light", "mqtt", "other_ieee",
        suggested_object_id="other_light",
        config_entry=entry,
        device_id=other_device.id,
    )
    hass.states.async_set("light.other_light", "off")
    add_z2m_entity(hass, entry, "light.kitchen")

    response = await call(
        hass, "turn_on_for", {"entity_id": ["light.kitchen", "light.other_light"], "duration": 5}
    )

    assert response["light.kitchen"] == SENT
    assert response["light.other_light"]["status"] == "unsupported"
    assert response["light.other_light"]["detail"] == "integration_not_supported"
    assert len(publishes) == 1
    assert publishes[0].data["topic"] == TOPIC


async def test_publish_error_rejects_that_target(hass, setup_production, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")
    async_mock_service(hass, "mqtt", "publish", raise_exception=Exception("broker unreachable"))

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 5})

    assert raised.value.translation_key == "all_targets_failed"


async def test_turn_on_error_rejects_that_target(hass, setup_production, publishes):
    """light.turn_on failure before mqtt.publish propagates as REJECTED."""
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")
    async_mock_service(hass, "light", "turn_on", raise_exception=Exception("entity unavailable"))

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 5, "brightness": 128})

    assert raised.value.translation_key == "all_targets_failed"
    assert not publishes  # publish was never reached


async def test_multiple_devices_each_get_their_own_topic(hass, setup_production, publishes, turn_ons):
    ieee1, ieee2 = "0x00124b0000000001", "0x00124b0000000002"
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.room1", ieee=ieee1)
    add_z2m_entity(hass, entry, "light.room2", ieee=ieee2)

    response = await call(
        hass, "turn_on_for", {"entity_id": ["light.room1", "light.room2"], "duration": 5}
    )

    assert response["light.room1"] == SENT
    assert response["light.room2"] == SENT
    topics = {p.data["topic"] for p in publishes}
    assert topics == {f"zigbee2mqtt/{ieee1}/set", f"zigbee2mqtt/{ieee2}/set"}


async def test_duration_below_50ms_is_clamped(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")

    response = await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": {"milliseconds": 20}})

    assert response == {"light.kitchen": {**SENT, "clamped_to": 0.05}}
    assert json.loads(publishes[0].data["payload"]) == {"state": "ON", "on_time": 0.1}


async def test_group_without_fields_publishes_to_group_id_topic(hass, setup_production, publishes, turn_ons):
    add_z2m_group(hass, z2m_entry(hass), "light.downstairs", group_id=7)

    response = await call(hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 5})

    assert response == {"light.downstairs": SENT}
    assert not turn_ons
    assert len(publishes) == 1
    assert publishes[0].data["topic"] == "zigbee2mqtt/7/set"
    assert json.loads(publishes[0].data["payload"]) == {"state": "ON", "on_time": 5.0}


async def test_group_with_fields_calls_turn_on_then_publishes(hass, setup_production, publishes, turn_ons):
    add_z2m_group(hass, z2m_entry(hass), "light.downstairs", group_id=7)

    response = await call(
        hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 5, "brightness": 128}
    )

    assert response == {"light.downstairs": SENT}
    assert turn_ons[0].data == {"entity_id": "light.downstairs", "brightness": 128}
    assert publishes[0].data["topic"] == "zigbee2mqtt/7/set"


async def test_group_on_custom_base_topic_is_not_addressable(hass, setup_production, publishes, turn_ons):
    add_z2m_group(hass, z2m_entry(hass), "light.downstairs", group_id=7, base_topic="z2m")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 5})

    assert raised.value.translation_placeholders["summary"] == "light.downstairs: not_addressable"
    assert not publishes


async def test_device_and_group_each_get_their_own_topic(hass, setup_production, publishes, turn_ons):
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")
    add_z2m_group(hass, entry, "light.downstairs", group_id=7)

    response = await call(
        hass, "turn_on_for", {"entity_id": ["light.kitchen", "light.downstairs"], "duration": 5}
    )

    assert response == {"light.kitchen": SENT, "light.downstairs": SENT}
    assert {p.data["topic"] for p in publishes} == {TOPIC, "zigbee2mqtt/7/set"}


# --- State read-backs ---


def _reads(publishes) -> list[str]:
    """Topics of the read-backs published so far, each checked to carry the read payload."""
    reads = [p for p in publishes if p.data["topic"].endswith("/get")]
    assert all(json.loads(p.data["payload"]) == {"state": ""} for p in reads)
    return [p.data["topic"] for p in reads]


def _now() -> datetime:
    """Wall-clock now, which async_fire_time_changed measures against (dt_util.utcnow can be frozen)."""
    return datetime.fromtimestamp(time.time(), UTC)


async def _advance(hass, start: datetime, seconds: float) -> None:
    async_fire_time_changed(hass, start + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_without_fields_reads_on_then_twice_after_the_timer(hass, setup_production, publishes, turn_ons):
    add_z2m_entity(hass, z2m_entry(hass), "light.kitchen")
    start = _now()

    await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 10})
    assert _reads(publishes) == []

    await _advance(hass, start, 1.5)
    assert _reads(publishes) == [GET_TOPIC]
    await _advance(hass, start, 10.5)
    assert _reads(publishes) == [GET_TOPIC]
    await _advance(hass, start, 11.5)
    assert _reads(publishes) == [GET_TOPIC] * 2
    await _advance(hass, start, 15.5)
    assert _reads(publishes) == [GET_TOPIC] * 3


async def test_with_fields_reads_only_after_the_timer(hass, setup_production, publishes, turn_ons):
    add_z2m_entity(hass, z2m_entry(hass), "light.kitchen")
    start = _now()

    await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 10, "brightness": 128})

    await _advance(hass, start, 1.5)
    assert _reads(publishes) == []
    await _advance(hass, start, 15.5)
    assert _reads(publishes) == [GET_TOPIC] * 2


async def test_late_end_read_scales_with_a_long_timer(hass, setup_production, publishes, turn_ons):
    """2% of 1000 s is 20 s, past the 5 s floor."""
    add_z2m_entity(hass, z2m_entry(hass), "light.kitchen")
    start = _now()

    await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 1000})

    await _advance(hass, start, 1001.5)
    assert len(_reads(publishes)) == 2  # the on read and the first end read
    await _advance(hass, start, 1019.5)
    assert len(_reads(publishes)) == 2
    await _advance(hass, start, 1020.5)
    assert len(_reads(publishes)) == 3


async def test_group_reads_its_group_topic(hass, setup_production, publishes, turn_ons):
    add_z2m_group(hass, z2m_entry(hass), "light.downstairs", group_id=7)
    start = _now()

    await call(hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 5})
    await _advance(hass, start, 10.5)

    assert _reads(publishes) == ["zigbee2mqtt/7/get"] * 3


async def test_a_second_call_replaces_the_pending_reads_of_that_target_only(
    hass, setup_production, publishes, turn_ons
):
    other_get = "zigbee2mqtt/0x00124b0000000002/get"
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.kitchen")
    add_z2m_entity(hass, entry, "light.hall", ieee="0x00124b0000000002")
    start = _now()

    await call(hass, "turn_on_for", {"entity_id": ["light.kitchen", "light.hall"], "duration": 10})
    await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 100, "brightness": 128})

    await _advance(hass, start, 15.5)
    assert _reads(publishes) == [other_get] * 3  # the kitchen's first schedule never fired
    await _advance(hass, start, 105.5)
    assert _reads(publishes) == [other_get] * 3 + [GET_TOPIC] * 2


async def test_unload_cancels_pending_reads(hass, setup_production, publishes, turn_ons):
    add_z2m_entity(hass, z2m_entry(hass), "light.kitchen")
    start = _now()

    await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 5})
    assert await hass.config_entries.async_unload(setup_production.entry_id)
    await _advance(hass, start, 10.5)

    assert _reads(publishes) == []


async def test_a_failed_read_is_logged_and_the_result_stays_sent(hass, setup_production, turn_ons, caplog):
    add_z2m_entity(hass, z2m_entry(hass), "light.kitchen")
    start = _now()
    sets = []

    async def publish(service_call):
        if service_call.data["topic"].endswith("/get"):
            raise HomeAssistantError("broker unreachable")
        sets.append(service_call)

    hass.services.async_register("mqtt", "publish", publish)

    response = await call(hass, "turn_on_for", {"entity_id": "light.kitchen", "duration": 5})
    with caplog.at_level(logging.DEBUG, logger="custom_components.device_side.integrations.zigbee2mqtt"):
        await _advance(hass, start, 10.5)

    assert response == {"light.kitchen": SENT}
    assert len(sets) == 1
    assert caplog.text.count("State read for light.kitchen failed: broker unreachable") == 3


# --- Direct helper tests (covering edge-case guards) ---


def _target(identifier: str) -> SimpleNamespace:
    device = MagicMock()
    device.identifiers = {("mqtt", identifier)}
    return SimpleNamespace(device=device)


def test_group_identifier_matches_z2m_encoding():
    """Pinned to the literal Z2M writes, so the test checks Z2M's scheme rather than our own."""
    assert topic(_target("zigbee2mqtt_1221051039810110150109113116116_7"), "set") == "zigbee2mqtt/7/set"


def test_is_z2m_group_true_for_any_base_topic(hass):
    assert is_z2m_group(hass, _target("zigbee2mqtt_1221051039810110150109113116116_7"))
    assert is_z2m_group(hass, _target("zigbee2mqtt_12250109_7"))


def test_is_z2m_group_false_for_a_device(hass):
    assert not is_z2m_group(hass, _target(f"zigbee2mqtt_{IEEE}"))
    assert not is_z2m_group(hass, SimpleNamespace(device=None))


def test_detect_returns_false_when_device_is_none(hass):
    entry = MagicMock()
    assert detect(hass, entry, None) is False


def test_detect_returns_false_when_identifier_prefix_does_not_match(hass):
    device = MagicMock()
    device.identifiers = {("mqtt", "other_bridge_0x1234")}
    assert detect(hass, MagicMock(), device) is False


def test_detect_returns_true_for_z2m_identifier(hass):
    device = MagicMock()
    device.identifiers = {("mqtt", f"zigbee2mqtt_{IEEE}")}
    assert detect(hass, MagicMock(), device) is True


def test_z2m_address_returns_none_when_no_matching_identifier():
    device = MagicMock()
    device.identifiers = {("mqtt", "other_bridge_0x1234"), ("zha", IEEE)}
    assert z2m_address(device) is None


def test_topic_returns_none_when_device_is_none():
    target = SimpleNamespace(device=None)
    assert topic(target, "set") is None


def test_topic_returns_none_when_identifier_does_not_match():
    device = MagicMock()
    device.identifiers = {("mqtt", "other_bridge_0x1234")}
    target = SimpleNamespace(device=device)
    assert topic(target, "set") is None


def test_topic_returns_set_topic_for_z2m_device():
    device = MagicMock()
    device.identifiers = {("mqtt", f"zigbee2mqtt_{IEEE}")}
    target = SimpleNamespace(device=device)
    assert topic(target, "set") == f"zigbee2mqtt/{IEEE}/set"


def test_supports_returns_super_reason_when_scope_refuses(hass):
    """Line 48: super().supports() returns non-None; the adapter propagates the reason."""
    import dataclasses

    from custom_components.device_side.actions.turn_on_for import TurnOnForRequest
    from custom_components.device_side.core.models import LightFields
    from custom_components.device_side.integrations.zigbee2mqtt.turn_on_for import Z2MTurnOnFor

    adapter = Z2MTurnOnFor()
    device = MagicMock()
    device.identifiers = {("mqtt", f"zigbee2mqtt_{IEEE}")}
    target = SimpleNamespace(
        entity_id="light.test",
        domain="light",
        device=device,
        entry=MagicMock(),
        config_entry=MagicMock(),
        state=None,
        via_group=None,
        via_wrapper=None,
        is_group=False,
    )
    # Request with brightness; temporarily restrict scope so brightness is not in scope.
    request = TurnOnForRequest(duration_s=5.0, light=LightFields(brightness=128))
    restricted_scope = dataclasses.replace(Z2MTurnOnFor.scope, fields=frozenset())
    original_scope = Z2MTurnOnFor.scope
    Z2MTurnOnFor.scope = restricted_scope
    try:
        assert adapter.supports(hass, request, target) == "fields_not_tested"
    finally:
        Z2MTurnOnFor.scope = original_scope
