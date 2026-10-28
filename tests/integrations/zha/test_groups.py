"""ZHA expand_group: a group entity's members, from the zha gateway's group and the entity registry."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_side.core.resolver import resolve
from custom_components.device_side.core.runtime import get_runtime
from custom_components.device_side.integrations.zha.addressing import group_id
from custom_components.device_side.integrations.zha.groups import expand_group, light_members

from ...fixtures.zha import add_zha_entity, zha_entry, zha_group

A, B, C = "00:00:00:00:00:00:00:0a", "00:00:00:00:00:00:00:0b", "00:00:00:00:00:00:00:0c"


def _group_target(hass, entity_id="light.zha_group"):
    return resolve(hass, get_runtime(hass).registry, entity_id)


async def test_members_in_the_group_entitys_domain(hass, setup_production, zha_groups):
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.zha_group", unique_id="light_zha_group_0x0002")
    add_zha_entity(hass, entry, "light.b", ieee=B)
    add_zha_entity(hass, entry, "light.a", ieee=A)
    add_zha_entity(hass, entry, "switch.plug", ieee=C, unique_id=f"{C}-1")
    zha_groups[2] = zha_group((B, 11), (A, 11), (C, 1), ("00:00:00:00:00:00:00:0d", 11))

    members = expand_group(hass, _group_target(hass))

    # The plug is in the switch group, and the last member has no entity: both are left out.
    assert [member.entity_id for member in members] == ["light.a", "light.b"]
    assert {member.via_group for member in members} == {"light.zha_group"}


async def test_a_member_that_cannot_resolve_is_dropped(hass, setup_production, zha_groups):
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.zha_group", unique_id="light_zha_group_0x0002")
    add_zha_entity(hass, entry, "light.b", ieee=B)
    unloaded = MockConfigEntry(domain="zha")
    unloaded.add_to_hass(hass)
    add_zha_entity(hass, unloaded, "light.a", ieee=A)  # resolve refuses it: integration_not_loaded
    zha_groups[2] = zha_group((A, 11), (B, 11))

    assert [member.entity_id for member in expand_group(hass, _group_target(hass))] == ["light.b"]


async def test_a_group_zha_no_longer_knows_is_empty(hass, setup_production, zha_groups):
    add_zha_entity(hass, zha_entry(hass), "light.zha_group", unique_id="light_zha_group_0x0002")

    assert expand_group(hass, _group_target(hass)) == []


async def test_light_members_are_every_light_the_group_holds(hass, setup_production, zha_groups):
    """Whether a call targets them or not: a groupcast reaches them all."""
    entry = zha_entry(hass)
    add_zha_entity(hass, entry, "light.a", ieee=A)
    add_zha_entity(hass, entry, "switch.plug", ieee=C, unique_id=f"{C}-1")
    zha_groups[2] = zha_group((A, 11), (C, 1), (B, 11))

    assert light_members(hass, 2) == {"light.a"}
    assert light_members(hass, 3) == frozenset()


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("light_zha_group_0x0002", 2),
        ("switch_zha_group_0xfff0", 0xFFF0),
        ("light_zha_group_0xzz", None),
        ("00:17:88:01:02:03:04:05-11", None),
    ],
)
def test_group_id(unique_id, expected):
    assert group_id(unique_id) == expected
