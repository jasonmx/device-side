"""Zigbee2MQTT turn_on_for: optional light.turn_on then mqtt.publish with on_time."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.integrations.zigbee2mqtt.addressing import command_topic, z2m_address
from custom_components.device_side.integrations.zigbee2mqtt.detect import detect

from ...conftest import call
from ...fixtures.z2m import IEEE, add_z2m_entity, z2m_entry

SENT = {"status": "sent", "integration": "zigbee2mqtt"}
TOPIC = f"zigbee2mqtt/{IEEE}/set"


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


# --- Direct helper tests (covering edge-case guards) ---


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


def test_command_topic_returns_none_when_device_is_none():
    target = SimpleNamespace(device=None)
    assert command_topic(target) is None


def test_command_topic_returns_none_when_identifier_does_not_match():
    device = MagicMock()
    device.identifiers = {("mqtt", "other_bridge_0x1234")}
    target = SimpleNamespace(device=device)
    assert command_topic(target) is None


def test_command_topic_returns_set_topic_for_z2m_device():
    device = MagicMock()
    device.identifiers = {("mqtt", f"zigbee2mqtt_{IEEE}")}
    target = SimpleNamespace(device=device)
    assert command_topic(target) == f"zigbee2mqtt/{IEEE}/set"


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
