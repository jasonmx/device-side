"""HA group-platform expansion, any domain."""

import pytest

from custom_components.device_side.core.groups import expand_ha_groups

from ..fixtures.fake import add_fake_native_group, add_ha_group, fake_config_entry


@pytest.mark.parametrize("domain", ["light", "switch"])
async def test_group_helper_expands_to_members(hass, domain):
    add_ha_group(hass, f"{domain}.room", [f"{domain}.a", f"{domain}.b"])

    members, empty = expand_ha_groups(hass, [f"{domain}.room", f"{domain}.c"])

    assert members == {f"{domain}.a": f"{domain}.room", f"{domain}.b": f"{domain}.room", f"{domain}.c": None}
    assert empty == []


async def test_nested_and_legacy_groups_dedupe_in_order(hass):
    add_ha_group(hass, "light.upstairs", ["light.a", "light.b"])
    add_ha_group(hass, "group.house", ["light.upstairs", "light.a", "light.c"])

    members, _ = expand_ha_groups(hass, ["group.house", "light.b"])

    assert members == {"light.a": "light.upstairs", "light.b": "light.upstairs", "light.c": "group.house"}


async def test_empty_group_is_reported(hass):
    add_ha_group(hass, "light.nobody", [])

    assert expand_ha_groups(hass, ["light.nobody"]) == ({}, ["light.nobody"])


async def test_self_reference_and_depth_limit_terminate(hass):
    add_ha_group(hass, "light.loop", ["light.loop", "light.inner"])
    add_ha_group(hass, "light.inner", ["light.loop"])

    members, _ = expand_ha_groups(hass, ["light.loop"])

    # The cycle stops at MAX_DEPTH; the group left over is passed on and resolves as unsupported.
    assert list(members) == ["light.loop"]


async def test_native_groups_are_left_alone(hass):
    add_fake_native_group(hass, fake_config_entry(hass), "light.fake_group", ["light.a"])

    assert expand_ha_groups(hass, ["light.fake_group"]) == ({"light.fake_group": None}, [])
