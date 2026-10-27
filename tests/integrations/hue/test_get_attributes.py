"""Hue get_attributes: one entry per target from aiohue's cache, keyed by entity_id as core's queries are.

Brightness is percent and the shape flat, as on hue_dimmer, so its templates read these responses unchanged.
"""

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.color import color_xy_to_hs, color_xy_to_RGB

from custom_components.device_side.integrations.hue.transition_cache import COLOR_TEMP, transition_cache

from ...conftest import call, refusal
from ...fixtures.hue import add_hue_entity, add_hue_group, hue_entry

pytestmark = pytest.mark.usefixtures("setup_production")


def colors(xy: tuple[float, float]) -> dict:
    return {"xy_color": list(xy), "rgb_color": list(color_xy_to_RGB(*xy)), "hs_color": list(color_xy_to_hs(*xy))}


async def room(hass, bridge, lights: dict[str, dict], brightness: float | None = None):
    """A room over the given lights (id -> light kwargs), with entities light.<id> and light.room."""
    for light_id, light in lights.items():
        bridge.light(light_id, **light)
    bridge.room("grouped-1", list(lights), brightness=brightness)
    entry = await hue_entry(hass, bridge)
    members = [add_hue_entity(hass, entry, f"light.{light_id}", light_id) for light_id in lights]
    add_hue_group(hass, entry, "light.room", "grouped-1", members)


async def test_light_row_uses_ha_attribute_names(hass, bridge):
    # Response names match set_attributes' fields and HA's attributes (hue_dimmer issue #16).
    bridge.light("light-1", on=False, brightness=40.0, mirek=370, xy=(0.4, 0.4))
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.lamp", "light-1")

    response = await call(hass, "get_attributes", {"entity_id": "light.lamp"})

    assert response == {"light.lamp": {"brightness": 40.0, "color_temp_kelvin": 2702, **colors((0.4, 0.4))}}


async def test_light_without_features_reports_what_it_has(hass, bridge):
    bridge.light("light-1", brightness=None, mirek=None)
    bridge.light("light-2", mirek=250, mirek_valid=False)  # in color mode: its mirek is stale
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.plug", "light-1")
    add_hue_entity(hass, entry, "light.lamp", "light-2")

    response = await call(hass, "get_attributes", {"entity_id": ["light.plug", "light.lamp"]})

    assert response == {"light.plug": {}, "light.lamp": {"brightness": 50.0}}


async def test_room_row_follows_the_bridge_while_lights_are_on(hass, bridge):
    await room(
        hass,
        bridge,
        {"one": {"on": True, "brightness": 20.0, "mirek": 250}, "two": {"on": True, "brightness": 80.0, "mirek": 500}},
        brightness=60.0,
    )

    response = await call(hass, "get_attributes", {"entity_id": "light.room"})

    assert response == {"light.room": {"brightness": 60.0, "color_temp_kelvin": 3000}}


async def test_room_row_averages_every_light_while_all_are_off(hass, bridge):
    await room(hass, bridge, {"one": {"brightness": 20.0, "mirek": 250}, "two": {"brightness": 60.0, "mirek": 500}})

    response = await call(hass, "get_attributes", {"entity_id": "light.room"})

    assert response["light.room"] == {"brightness": 40.0, "color_temp_kelvin": 3000}


async def test_room_row_counts_only_the_lights_that_are_on(hass, bridge):
    await room(
        hass,
        bridge,
        {"one": {"on": True, "brightness": 20.0, "mirek": 250}, "two": {"brightness": 90.0, "mirek": 500}},
        brightness=20.0,
    )

    response = await call(hass, "get_attributes", {"entity_id": "light.room"})

    assert response["light.room"] == {"brightness": 20.0, "color_temp_kelvin": 4000}


async def test_room_row_with_mixed_color_modes(hass, bridge):
    await room(
        hass,
        bridge,
        {
            "white": {"on": True, "mirek": 250, "xy": (0.3, 0.3)},
            "red": {"on": True, "mirek": 153, "mirek_valid": False, "xy": (0.6, 0.3)},
        },
        brightness=50.0,
    )

    response = await call(hass, "get_attributes", {"entity_id": "light.room"})

    assert response["light.room"] == {"brightness": 50.0, "color_temp_kelvin": 4000, **colors((0.45, 0.3))}


async def test_one_entry_per_target(hass, bridge):
    # A room's lights get entries only when targeted, as on hue_dimmer, so merge_response lists each target once.
    await room(hass, bridge, {"one": {}, "two": {}})

    response = await call(hass, "get_attributes", {"entity_id": ["light.room", "light.one"]})

    assert set(response) == {"light.room", "light.one"}
    assert response["light.one"] == {"brightness": 50.0, "color_temp_kelvin": 2702}


async def test_empty_room_and_missing_light_fail(hass, bridge):
    bridge.room("grouped-1", [])
    entry = await hue_entry(hass, bridge)
    add_hue_group(hass, entry, "light.room", "grouped-1", [])
    add_hue_entity(hass, entry, "light.gone", "light-gone")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_attributes", {"entity_id": ["light.room", "light.gone"]})

    # empty_group is skipped silently; only the device failure raises.
    assert raised.value.translation_placeholders["summary"] == "light.gone: not_on_bridge"


async def test_query_raises_when_any_target_fails(hass, bridge):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.lamp", "light-1")
    add_hue_entity(hass, entry, "light.gone", "light-gone")

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "get_attributes", {"entity_id": ["light.lamp", "light.gone"]})

    # Any rejected target raises targets_failed, even when others succeeded.
    assert raised.value.translation_placeholders["summary"] == "light.gone: not_on_bridge"


async def test_v1_bridge_is_refused(hass, bridge):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge, api_version=1)
    add_hue_entity(hass, entry, "light.lamp", "light-1")

    assert await refusal(hass, "get_attributes", {"entity_id": "light.lamp"}) == "bridge_v1"


async def test_color_temp_reads_the_prediction_mid_move(hass, bridge, clock):
    # The bridge reports the end value at once; the light and room rows read where the lights are.
    await room(
        hass,
        bridge,
        {"one": {"on": True, "mirek": 454}, "two": {"on": True, "mirek": 454}, "three": {"on": True, "mirek": None}},
    )
    cache = transition_cache(hass)
    cache.moving("one", COLOR_TEMP, 254.0, 454.0, 10.0)
    cache.moving("two", COLOR_TEMP, 354.0, 454.0, 10.0)
    clock.now += 5.0  # one at 354, two at 404

    response = await call(hass, "get_attributes", {"entity_id": ["light.room", "light.one", "light.two"]})

    assert response["light.one"]["color_temp_kelvin"] == 2824
    assert response["light.two"]["color_temp_kelvin"] == 2475
    assert response["light.room"]["color_temp_kelvin"] == 2650
