"""ZHA turn_on_for: optional light.turn_on, OnWithTimedOff through issue_zigbee_cluster_command (or one
issue_zigbee_group_command for a ZHA group's members), then an OnOff and OnTime read-back."""

from unittest.mock import AsyncMock

import probatio
import pytest
from homeassistant.core import Context, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.device_side.const import DOMAIN
from custom_components.device_side.integrations.zha import zcl
from custom_components.device_side.integrations.zha.addressing import address

from ...conftest import call, refusal
from ...fixtures.zha import IEEE, add_zha_entity, zha_entry, zha_group

CONFIRMED = {"status": "confirmed", "integration": "zha"}


def reads(remaining, on=True) -> dict:
    """What zcl.read_attributes returns: OnOff, and OnTime in tenths."""
    return {zcl.ON_OFF: on, zcl.ON_TIME: remaining}


@pytest.fixture(autouse=True)
def readback(monkeypatch):
    """zcl.read_attributes, reading back on with the 5 s every test requests unless it sets its own."""
    read = AsyncMock(return_value=reads(50))
    monkeypatch.setattr(zcl, "read_attributes", read)
    return read


@pytest.fixture
def commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_cluster_command")


@pytest.fixture
def turn_ons(hass):
    return async_mock_service(hass, "light", "turn_on")


async def test_light_sends_on_with_timed_off(hass, setup_production, commands, turn_ons):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": CONFIRMED}
    assert not turn_ons
    assert len(commands) == 1
    assert commands[0].data == {
        "ieee": IEEE,
        "endpoint_id": 11,
        "cluster_id": 6,
        "cluster_type": "in",
        "command": 0x42,
        "command_type": "server",
        "params": {"on_off_control": 0, "on_time": 50, "off_wait_time": 0},
    }


async def test_brightness_calls_turn_on_first(hass, setup_production, commands, turn_ons):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5, "brightness": 128})

    assert response == {"light.bulb": CONFIRMED}
    assert turn_ons[0].data == {"entity_id": "light.bulb", "brightness": 128}
    assert len(commands) == 1


async def test_untested_field_is_refused(hass, setup_production, commands, turn_ons):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")

    data = {"entity_id": "light.bulb", "duration": 5, "hs_color": [30, 50]}
    assert await refusal(hass, "turn_on_for", data) == "fields_not_tested"
    assert not commands


async def test_duration_in_tenths_and_clamped(hass, setup_production, commands, turn_ons, readback):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")
    readback.return_value = reads(65534)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": {"hours": 2}})

    assert response == {"light.bulb": {**CONFIRMED, "clamped_to": 6553.4}}
    assert commands[0].data["params"]["on_time"] == 65534


@pytest.mark.parametrize("remaining", [50, 20])
async def test_on_time_within_slack_confirms(hass, setup_production, commands, readback, remaining):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")
    readback.return_value = reads(remaining)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": CONFIRMED}
    readback.assert_awaited_once_with(hass, (IEEE, 11), 0x0006, (0x0000,), optional=(0x4001,))


@pytest.mark.parametrize("remaining", [0, 51, 19])
async def test_on_time_outside_slack_is_sent(hass, setup_production, commands, readback, remaining):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")
    readback.return_value = reads(remaining)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": {"status": "sent", "integration": "zha", "detail": "timer_not_reported"}}


async def test_a_running_timer_on_a_device_that_stayed_off_is_sent(hass, setup_production, commands, readback):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")
    readback.return_value = reads(50, on=False)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": {"status": "sent", "integration": "zha", "detail": "not_on"}}


@pytest.mark.parametrize(
    "read",
    [
        {"side_effect": ImportError("No module named 'zha'")},
        {"side_effect": LookupError("ZHA device not found")},
        {"return_value": reads(None)},  # an uncomparable OnTime
        {"return_value": reads(50, on=None)},  # an OnOff that is neither on nor off
        {"return_value": {}},  # a value missing
    ],
)
async def test_failed_read_is_sent(hass, setup_production, commands, readback, read):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")
    readback.configure_mock(**read)

    response = await call(hass, "turn_on_for", {"entity_id": "light.bulb", "duration": 5})

    assert response == {"light.bulb": {"status": "sent", "integration": "zha", "detail": "readback_failed"}}


async def test_switch_is_out_of_scope(hass, setup_production, commands, turn_ons):
    add_zha_entity(hass, zha_entry(hass), "switch.plug")

    assert await refusal(hass, "turn_on_for", {"entity_id": "switch.plug", "duration": 5}) == "domain_not_tested"


async def test_entity_without_a_light_unique_id_is_not_addressable(hass, setup_production, commands, turn_ons):
    add_zha_entity(hass, zha_entry(hass), "light.quirk", unique_id=f"{IEEE}-1-6-child_lock")

    assert await refusal(hass, "turn_on_for", {"entity_id": "light.quirk", "duration": 5}) == "not_addressable"


async def test_zha_error_rejects_that_target(hass, setup_production, turn_ons):
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.gone", ieee="00:00:00:00:00:00:00:01")
    add_zha_entity(hass, entry, "light.bulb")

    # A plain handler, since a mock service can't raise; the admin check has its own tests below.
    async def handler(service: ServiceCall) -> None:
        if service.data["ieee"] != IEEE:
            raise ValueError(f"Device with IEEE {service.data['ieee']} not found")

    hass.services.async_register("zha", "issue_zigbee_cluster_command", handler)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": ["light.bulb", "light.gone"], "duration": 5})

    assert raised.value.translation_key == "targets_failed"
    assert "light.gone: error" in raised.value.translation_placeholders["summary"]


@pytest.fixture
def admin_command(hass):
    """ZHA's real registration: an admin service, which checks the caller's context."""
    calls: list[ServiceCall] = []

    async def handler(service: ServiceCall) -> None:
        calls.append(service)

    schema = probatio.Schema({}, extra=probatio.ALLOW_EXTRA)
    async_register_admin_service(hass, "zha", "issue_zigbee_cluster_command", handler, schema)
    return calls


async def _call_as(hass, user) -> dict:
    return await hass.services.async_call(
        DOMAIN,
        "turn_on_for",
        {"entity_id": "light.bulb", "duration": 5},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def test_admin_caller_reaches_zha(hass, setup_production, admin_command, hass_admin_user):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")

    assert await _call_as(hass, hass_admin_user) == {"light.bulb": CONFIRMED}
    assert admin_command[0].context.user_id == hass_admin_user.id


async def test_non_admin_caller_is_refused_by_zha(hass, setup_production, admin_command, hass_read_only_user, readback):
    add_zha_entity(hass, zha_entry(hass), "light.bulb")

    with pytest.raises(HomeAssistantError) as raised:
        await _call_as(hass, hass_read_only_user)

    assert raised.value.translation_placeholders["summary"] == "light.bulb: admin_required"
    assert not admin_command
    readback.assert_not_awaited()


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        (f"{IEEE}-11", (IEEE, 11)),
        (f"{IEEE}-1-6", None),
        (f"{IEEE}-x", None),
        ("light_zha_group_0x0002", None),
    ],
)
def test_address(unique_id, expected):
    assert address(unique_id) == expected


A, B = "00:00:00:00:00:00:00:0a", "00:00:00:00:00:00:00:0b"


@pytest.fixture
def group_commands(hass):
    return async_mock_service(hass, "zha", "issue_zigbee_group_command")


@pytest.fixture
def two_light_group(hass, zha_groups):
    """light.zha_group, ZHA group 2, of light.a and light.b."""
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.zha_group", unique_id="light_zha_group_0x0002")
    add_zha_entity(hass, entry, "light.a", ieee=A)
    add_zha_entity(hass, entry, "light.b", ieee=B)
    zha_groups[2] = zha_group((A, 11), (B, 11))
    return entry


async def test_group_members_get_one_groupcast_and_a_read_back_each(
    hass, setup_production, two_light_group, commands, group_commands, turn_ons, readback
):
    response = await call(hass, "turn_on_for", {"entity_id": "light.zha_group", "duration": 5})

    assert response == {"light.a": CONFIRMED, "light.b": CONFIRMED}
    assert [command.data for command in group_commands] == [
        {"group": 2, "cluster_id": 6, "command": 0x42, "args": [0, 50, 0]}
    ]
    assert not commands
    assert not turn_ons
    assert sorted(read.args[1].ieee for read in readback.await_args_list) == [A, B]


async def test_group_fields_turn_on_the_group_entity_once(
    hass, setup_production, two_light_group, group_commands, turn_ons
):
    await call(hass, "turn_on_for", {"entity_id": "light.zha_group", "duration": 5, "brightness": 120})

    assert [turn_on.data for turn_on in turn_ons] == [{"entity_id": "light.zha_group", "brightness": 120}]
    assert len(group_commands) == 1


@pytest.mark.parametrize(("on", "detail"), [(False, "not_on"), (True, "timer_not_reported")])
async def test_a_member_without_on_time_reports_no_timer(
    hass, setup_production, two_light_group, group_commands, readback, on, detail
):
    """A member that can't run the timer drops the groupcast silently; its read-back says so."""
    readback.side_effect = lambda hass, addr, *args, **kwargs: {zcl.ON_OFF: on} if addr.ieee == B else reads(50)

    response = await call(hass, "turn_on_for", {"entity_id": "light.zha_group", "duration": 5})

    assert response == {"light.a": CONFIRMED, "light.b": {"status": "sent", "integration": "zha", "detail": detail}}


async def test_a_group_zha_no_longer_knows_is_skipped_as_empty(hass, setup_production, zha_groups, group_commands):
    add_zha_entity(hass, zha_entry(hass), "light.zha_group", unique_id="light_zha_group_0x0002")

    await call(hass, "turn_on_for", {"entity_id": "light.zha_group", "duration": 5}, return_response=False)

    assert not group_commands


async def test_a_light_named_directly_or_through_an_ha_group_gets_its_own_command(
    hass, setup_production, two_light_group, commands, group_commands
):
    add_zha_entity(hass, two_light_group, "light.bulb")
    hass.states.async_set("group.room", "on", {"entity_id": ["light.bulb"]})

    response = await call(hass, "turn_on_for", {"entity_id": ["group.room", "light.zha_group"], "duration": 5})

    assert response == {"light.bulb": CONFIRMED, "light.a": CONFIRMED, "light.b": CONFIRMED}
    assert [command.data["ieee"] for command in commands] == [IEEE]
    assert len(group_commands) == 1


async def test_non_admin_caller_is_refused_for_every_member(
    hass, setup_production, two_light_group, hass_read_only_user, readback
):
    calls: list[ServiceCall] = []

    async def handler(service: ServiceCall) -> None:
        calls.append(service)

    schema = probatio.Schema({}, extra=probatio.ALLOW_EXTRA)
    async_register_admin_service(hass, "zha", "issue_zigbee_group_command", handler, schema)

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "turn_on_for",
            {"entity_id": "light.zha_group", "duration": 5},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )

    assert raised.value.translation_placeholders["summary"] == "light.a: admin_required, light.b: admin_required"
    assert not calls
    readback.assert_not_awaited()


async def test_a_failed_groupcast_rejects_only_that_groups_members(
    hass, setup_production, two_light_group, commands, readback
):
    add_zha_entity(hass, two_light_group, "light.bulb")

    async def handler(service: ServiceCall) -> None:
        raise ValueError("broadcast table full")

    hass.services.async_register("zha", "issue_zigbee_group_command", handler)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "turn_on_for", {"entity_id": ["light.bulb", "light.zha_group"], "duration": 5})

    # light.bulb was confirmed, so it is not among the failures.
    assert raised.value.translation_placeholders["summary"] == "light.a: error, light.b: error"
