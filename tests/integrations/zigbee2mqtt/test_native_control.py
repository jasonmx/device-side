"""Zigbee2MQTT turn_on_for: turning on hue_native_control before a timer with a color."""

import logging

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from ...conftest import call
from ...fixtures.z2m import GROUPS, IEEE, INFO, add_z2m_entity, add_z2m_group, z2m_entry

SENT = {"status": "sent", "integration": "zigbee2mqtt"}
DEVICE_REQUEST = "zigbee2mqtt/bridge/request/device/options"
DEVICE_RESPONSE = "zigbee2mqtt/bridge/response/device/options"
GROUP_REQUEST = "zigbee2mqtt/bridge/request/group/options"
GROUP_RESPONSE = "zigbee2mqtt/bridge/response/group/options"
MEMBER = "0x00124b00aaaaaaaa"
LOGGER = "custom_components.device_side.integrations.zigbee2mqtt"


@pytest.fixture
def turn_ons(hass):
    return async_mock_service(hass, "light", "turn_on")


def hue_bulb(hass, entity_id: str = "light.lamp", manufacturer: str = "Philips") -> str:
    return add_z2m_entity(hass, z2m_entry(hass), entity_id, manufacturer=manufacturer)


async def test_hue_bulb_with_option_off_gets_it_before_the_timer(hass, setup_production, broker, turn_ons, caplog):
    hue_bulb(hass)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert response == {"light.lamp": SENT}
    [request] = broker.requests()
    assert request["topic"] == DEVICE_REQUEST
    assert request["payload"]["id"] == IEEE
    assert request["payload"]["options"] == {"hue_native_control": True}
    assert broker.published.index(request) < broker.published.index(broker.timers()[0])
    assert len(turn_ons) == 1
    assert "Turned on Zigbee2MQTT's hue_native_control for light.lamp" in caplog.text
    assert not broker.listening(DEVICE_RESPONSE) and not broker.listening(INFO)


@pytest.mark.parametrize("field", [{"color_temp_kelvin": 3000}, {"hs_color": [120, 100]}, {"xy_color": [0.2, 0.3]}])
async def test_every_color_field_triggers_it(hass, setup_production, broker, turn_ons, field):
    hue_bulb(hass)

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, **field})

    assert len(broker.requests()) == 1


async def test_option_already_on_sends_no_request(hass, setup_production, broker, turn_ons):
    hue_bulb(hass)
    broker.retained[INFO]["config"]["devices"][IEEE]["hue_native_control"] = True

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert broker.requests() == []
    assert len(broker.timers()) == 1


async def test_device_missing_from_settings_gets_the_request(hass, setup_production, broker, turn_ons):
    hue_bulb(hass)
    broker.retained[INFO] = {"config": {}}

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert len(broker.requests()) == 1


async def test_other_brands_are_left_alone(hass, setup_production, broker, turn_ons):
    hue_bulb(hass, manufacturer="IKEA of Sweden")

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert broker.requests() == []
    assert broker.topics == []
    assert len(broker.timers()) == 1


@pytest.mark.parametrize("fields", [{}, {"brightness": 128}, {"transition": 1}])
async def test_without_a_color_nothing_is_read(hass, setup_production, broker, turn_ons, fields):
    hue_bulb(hass)

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, **fields})

    assert broker.requests() == []
    assert broker.topics == []


async def test_no_bridge_info_warns_and_still_sends(hass, setup_production, broker, turn_ons, caplog):
    hue_bulb(hass)
    del broker.retained[INFO]

    response = await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert response == {"light.lamp": SENT}
    assert broker.requests() == []
    assert len(broker.timers()) == 1
    assert "may light at its last color first: no bridge/info from Zigbee2MQTT" in caplog.text


async def test_no_reply_warns_and_still_sends(hass, setup_production, broker, turn_ons, caplog):
    hue_bulb(hass)
    broker.reply = None

    response = await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert response == {"light.lamp": SENT}
    assert len(broker.timers()) == 1
    assert "Couldn't turn on Zigbee2MQTT's hue_native_control for light.lamp" in caplog.text
    assert caplog.text.rstrip().endswith("no reply from Zigbee2MQTT")
    assert not broker.listening(DEVICE_RESPONSE)


async def test_error_reply_warns_with_z2m_error_and_still_sends(hass, setup_production, broker, turn_ons, caplog):
    hue_bulb(hass)
    broker.reply = {"status": "error", "error": "Device 'x' does not exist"}

    response = await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert response == {"light.lamp": SENT}
    assert len(broker.timers()) == 1
    assert "may light at its last color first: Device 'x' does not exist" in caplog.text


async def test_reply_without_status_warns(hass, setup_production, broker, turn_ons, caplog):
    hue_bulb(hass)
    broker.reply = {}

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert "may light at its last color first: status None" in caplog.text


async def test_unreadable_reply_is_ignored(hass, setup_production, broker, turn_ons, caplog):
    hue_bulb(hass)
    broker.reply = "not json"

    await call(hass, "turn_on_for", {"entity_id": "light.lamp", "duration": 6, "rgb_color": [255, 0, 0]})

    assert "may light at its last color first: no reply from Zigbee2MQTT" in caplog.text
    assert len(broker.timers()) == 1


BRIDGE_GROUPS = [{"id": 3, "members": []}, {"id": 7, "members": [{"ieee_address": MEMBER, "endpoint": 11}]}]


def group_with_member(hass, manufacturer: str) -> None:
    entry = z2m_entry(hass)
    add_z2m_entity(hass, entry, "light.member", ieee=MEMBER, manufacturer=manufacturer)
    add_z2m_group(hass, entry, "light.downstairs", group_id=7)


async def test_group_with_a_hue_member_gets_the_group_option(hass, setup_production, broker, turn_ons, caplog):
    group_with_member(hass, "Philips")
    broker.retained[GROUPS] = BRIDGE_GROUPS
    broker.retained[INFO]["config"]["devices"][MEMBER] = {"hue_native_control": True}  # a member's own doesn't count

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = await call(
            hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 6, "rgb_color": [255, 0, 0]}
        )

    assert response == {"light.downstairs": SENT}
    [request] = broker.requests()
    assert request["topic"] == GROUP_REQUEST
    assert request["payload"]["id"] == "7"
    assert "Turned on Zigbee2MQTT's hue_native_control for light.downstairs" in caplog.text
    assert not broker.listening(GROUP_RESPONSE)


async def test_group_with_option_on_sends_no_request(hass, setup_production, broker, turn_ons):
    group_with_member(hass, "Philips")
    broker.retained[GROUPS] = BRIDGE_GROUPS
    broker.retained[INFO]["config"]["groups"]["7"] = {"hue_native_control": True}

    await call(hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 6, "rgb_color": [255, 0, 0]})

    assert broker.requests() == []


async def test_group_without_a_hue_member_is_left_alone(hass, setup_production, broker, turn_ons):
    group_with_member(hass, "IKEA of Sweden")
    broker.retained[GROUPS] = BRIDGE_GROUPS

    await call(hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 6, "rgb_color": [255, 0, 0]})

    assert broker.requests() == []
    assert len(broker.timers()) == 1


async def test_group_missing_from_bridge_groups_is_left_alone(hass, setup_production, broker, turn_ons):
    group_with_member(hass, "Philips")
    broker.retained[GROUPS] = [{"id": 3, "members": []}]

    await call(hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 6, "rgb_color": [255, 0, 0]})

    assert broker.requests() == []


async def test_no_bridge_groups_warns_and_still_sends(hass, setup_production, broker, turn_ons, caplog):
    group_with_member(hass, "Philips")

    response = await call(
        hass, "turn_on_for", {"entity_id": "light.downstairs", "duration": 6, "rgb_color": [255, 0, 0]}
    )

    assert response == {"light.downstairs": SENT}
    assert len(broker.timers()) == 1
    assert "may light at its last color first: no bridge/groups from Zigbee2MQTT" in caplog.text
