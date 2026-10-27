"""Hue set_attributes: one light PUT per light, rooms written light by light, ported from hue_dimmer's tests.

Brightness is percent, as on hue_dimmer, so the bridge gets it unchanged.
"""

import probatio
import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy

from ...conftest import call
from ...fixtures.hue import add_hue_entity, add_hue_group, hue_entry

pytestmark = pytest.mark.usefixtures("setup_production")

SENT = {"status": "sent", "integration": "hue"}
CT_LIGHT = {"mirek": 370}
COLOR_LIGHT = {"mirek": 370, "xy": (0.4, 0.4)}
WHITE_LIGHT = {"mirek": None}


def color(xy):
    return {"color": {"xy": {"x": xy[0], "y": xy[1]}}}


async def lamp(hass, bridge, **light):
    bridge.light("light-1", **light)
    entry = await hue_entry(hass, bridge)
    return add_hue_entity(hass, entry, "light.lamp", "light-1")


@pytest.mark.parametrize(
    ("data", "light", "put", "detail"),
    [
        pytest.param({"brightness": 40}, CT_LIGHT, {"dimming": {"brightness": 40.0}}, None, id="brightness_only"),
        pytest.param({"color_temp_kelvin": 3000}, CT_LIGHT, {"color_temperature": {"mirek": 333}}, None, id="ct_only"),
        pytest.param(
            {"brightness": 20, "color_temp_kelvin": 4000},
            CT_LIGHT,
            {"dimming": {"brightness": 20.0}, "color_temperature": {"mirek": 250}},
            None,
            id="brightness_and_ct",
        ),
        pytest.param(
            {"brightness": 40, "color_temp_kelvin": 3000},
            WHITE_LIGHT,
            {"dimming": {"brightness": 40.0}},
            "fields_dropped",
            id="ct_on_white_light_brightness_still_sent",
        ),
        pytest.param(
            {"color_temp_kelvin": 1000}, CT_LIGHT, {"color_temperature": {"mirek": 454}}, None, id="ct_clamped_to_min"
        ),
        pytest.param(
            {"color_temp_kelvin": 9000}, CT_LIGHT, {"color_temperature": {"mirek": 153}}, None, id="ct_clamped_to_max"
        ),
        pytest.param({"xy_color": [0.369, 0.445]}, COLOR_LIGHT, color((0.369, 0.445)), None, id="xy_color"),
        pytest.param({"hs_color": [30, 80]}, COLOR_LIGHT, color(color_hs_to_xy(30, 80)), None, id="hs_color"),
        pytest.param(
            {"rgb_color": [255, 128, 0]}, COLOR_LIGHT, color(color_RGB_to_xy(255, 128, 0)), None, id="rgb_color"
        ),
        pytest.param(
            {"xy_color": [0.3, 0.3], "brightness": 40},
            CT_LIGHT,
            {"dimming": {"brightness": 40.0}},
            "fields_dropped",
            id="color_on_ct_light_brightness_still_sent",
        ),
    ],
)
async def test_single_light(hass, bridge, data, light, put, detail):
    await lamp(hass, bridge, **light)

    response = await call(hass, "set_attributes", {"entity_id": "light.lamp", **data})

    assert response == {"light.lamp": SENT | ({"detail": detail} if detail else {})}
    assert bridge.puts == [("light/light-1", put)]


async def test_writes_while_off_without_turning_on(hass, bridge):
    await lamp(hass, bridge, on=False)

    await call(hass, "set_attributes", {"entity_id": "light.lamp", "brightness": 100})

    assert bridge.puts == [("light/light-1", {"dimming": {"brightness": 100.0}})]


@pytest.mark.parametrize(
    ("data", "light"),
    [
        pytest.param({"color_temp_kelvin": 3000}, WHITE_LIGHT, id="ct_on_white_light"),
        pytest.param({"xy_color": [0.3, 0.3]}, CT_LIGHT, id="color_on_ct_light"),
        pytest.param({"brightness": 40}, {"brightness": None, "mirek": None}, id="brightness_on_on_off_light"),
    ],
)
async def test_nothing_the_light_can_take_is_unsupported(hass, bridge, data, light):
    await lamp(hass, bridge, **light)

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_attributes", {"entity_id": "light.lamp", **data})

    assert raised.value.translation_placeholders["summary"] == "light.lamp: fields_not_supported"
    assert bridge.puts == []


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({}, id="no_fields"),
        pytest.param({"min_brightness": 0, "max_brightness": 0, "color_temp_kelvin": 0}, id="only_zeros"),
    ],
)
async def test_nothing_to_set_is_refused(hass, bridge, data):
    await lamp(hass, bridge)

    with pytest.raises(ServiceValidationError) as raised:
        await call(hass, "set_attributes", {"entity_id": "light.lamp", **data})

    assert raised.value.translation_key == "nothing_to_set"


async def test_zero_leaves_a_limit_or_color_temperature_unset(hass, bridge):
    # As on hue_dimmer, so a template can pass 0 for "no limit".
    await lamp(hass, bridge, brightness=80.0)

    await call(
        hass,
        "set_attributes",
        {"entity_id": "light.lamp", "min_brightness": 0, "max_brightness": 30, "color_temp_kelvin": 0},
    )

    assert bridge.puts == [("light/light-1", {"dimming": {"brightness": 30.0}})]


async def test_several_colors_rgb_wins_then_hs(hass, bridge):
    # hue_dimmer took several colors and chose one; light.turn_on's one-color rule would refuse the call.
    await lamp(hass, bridge, **COLOR_LIGHT)

    await call(
        hass,
        "set_attributes",
        {"entity_id": "light.lamp", "rgb_color": [255, 0, 0], "hs_color": [120, 100], "xy_color": [0.2, 0.2]},
    )
    await call(hass, "set_attributes", {"entity_id": "light.lamp", "hs_color": [120, 100], "xy_color": [0.2, 0.2]})

    assert bridge.puts == [
        ("light/light-1", color(color_RGB_to_xy(255, 0, 0))),
        ("light/light-1", color(color_hs_to_xy(120, 100))),
    ]


async def test_brightness_zero_goes_to_the_bridge(hass, bridge):
    # Unlike the limits, 0 is a brightness: the bridge sets the light's lowest level, as under hue_dimmer.
    await lamp(hass, bridge)

    await call(hass, "set_attributes", {"entity_id": "light.lamp", "brightness": 0})

    assert bridge.puts == [("light/light-1", {"dimming": {"brightness": 0.0}})]


async def test_brightness_over_100_percent_is_invalid(hass, bridge):
    await lamp(hass, bridge)

    with pytest.raises(probatio.Invalid):
        await call(hass, "set_attributes", {"entity_id": "light.lamp", "brightness": 101})


@pytest.mark.parametrize(
    ("data", "brightness", "put"),
    [
        pytest.param({"min_brightness": 50}, 20.0, {"dimming": {"brightness": 50.0}}, id="min_raises"),
        pytest.param({"max_brightness": 30}, 80.0, {"dimming": {"brightness": 30.0}}, id="max_lowers"),
        pytest.param(
            {"min_brightness": 10, "max_brightness": 30}, 80.0, {"dimming": {"brightness": 30.0}}, id="both_lowers"
        ),
        pytest.param({"brightness": 20, "min_brightness": 50}, 80.0, {"dimming": {"brightness": 20.0}}, id="explicit"),
    ],
)
async def test_brightness_limits_clamp_the_stored_brightness(hass, bridge, data, brightness, put):
    await lamp(hass, bridge, on=False, brightness=brightness)

    response = await call(hass, "set_attributes", {"entity_id": "light.lamp", **data})

    assert response == {"light.lamp": SENT}
    assert bridge.puts == [("light/light-1", put)]


async def test_brightness_already_within_limits_writes_nothing(hass, bridge):
    await lamp(hass, bridge, brightness=70.0)

    response = await call(hass, "set_attributes", {"entity_id": "light.lamp", "min_brightness": 50})

    assert response == {"light.lamp": {"status": "unchanged", "integration": "hue", "detail": "within_limits"}}
    assert bridge.puts == []


async def test_one_failing_light_does_not_stop_the_others(hass, bridge):
    bridge.light("light-1")
    bridge.light("light-2")
    bridge.failing.add("light-1")
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.one", "light-1")
    add_hue_entity(hass, entry, "light.two", "light-2")

    response = await call(hass, "set_attributes", {"entity_id": ["light.one", "light.two"], "brightness": 40})

    assert response == {"light.one": {"status": "rejected", "integration": "hue", "detail": "error"}, "light.two": SENT}


async def test_light_gone_from_the_bridge_is_rejected(hass, bridge):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.lamp", "light-1")
    add_hue_entity(hass, entry, "light.gone", "light-gone")

    response = await call(hass, "set_attributes", {"entity_id": ["light.lamp", "light.gone"], "brightness": 40})

    assert response["light.gone"] == {"status": "rejected", "integration": "hue", "detail": "not_on_bridge"}


async def test_room_is_written_light_by_light(hass, bridge):
    bridge.light("light-1", **COLOR_LIGHT)
    bridge.light("light-2", **COLOR_LIGHT)
    bridge.light("light-3")  # in the room, but HA has no entity for it
    bridge.room("grouped-1", ["light-1", "light-2", "light-3"])
    entry = await hue_entry(hass, bridge)
    add_hue_entity(hass, entry, "light.one", "light-1")
    add_hue_entity(hass, entry, "light.two", "light-2")
    add_hue_group(hass, entry, "light.room", "grouped-1", ["light.one", "light.two"])

    response = await call(hass, "set_attributes", {"entity_id": "light.room", "xy_color": [0.369, 0.445]})

    assert response == {"light.one": SENT, "light.two": SENT}
    assert bridge.puts == [("light/light-1", color((0.369, 0.445))), ("light/light-2", color((0.369, 0.445)))]


async def test_empty_room_is_unsupported(hass, bridge):
    bridge.room("grouped-1", [])
    entry = await hue_entry(hass, bridge)
    add_hue_group(hass, entry, "light.room", "grouped-1", [])

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_attributes", {"entity_id": "light.room", "brightness": 40})

    assert raised.value.translation_placeholders["summary"] == "light.room: empty_group"


async def test_v1_bridge_is_refused(hass, bridge):
    bridge.light("light-1")
    entry = await hue_entry(hass, bridge, api_version=1)
    add_hue_entity(hass, entry, "light.lamp", "light-1")
    add_hue_group(hass, entry, "light.room", "grouped-1", ["light.lamp"])

    with pytest.raises(HomeAssistantError) as raised:
        await call(hass, "set_attributes", {"entity_id": ["light.lamp", "light.room"], "brightness": 40})

    assert raised.value.translation_placeholders["summary"] == "light.lamp: bridge_v1, light.room: bridge_v1"
    assert bridge.puts == []


GAMUT_C = {"red": {"x": 0.6915, "y": 0.3083}, "green": {"x": 0.17, "y": 0.7}, "blue": {"x": 0.1532, "y": 0.0475}}


async def test_color_inside_the_gamut_is_sent_unchanged(hass, bridge):
    await lamp(hass, bridge, xy=(0.4, 0.4), gamut=GAMUT_C)

    await call(hass, "set_attributes", {"entity_id": "light.lamp", "xy_color": [0.4, 0.4]})

    assert bridge.puts == [("light/light-1", color((0.4, 0.4)))]


async def test_color_outside_the_gamut_is_sent_at_the_nearest_edge(hass, bridge):
    await lamp(hass, bridge, xy=(0.4, 0.4), gamut=GAMUT_C)

    await call(hass, "set_attributes", {"entity_id": "light.lamp", "xy_color": [0.1, 0.9]})

    ((_, put),) = bridge.puts
    sent = (put["color"]["xy"]["x"], put["color"]["xy"]["y"])
    assert sent == pytest.approx((0.17, 0.7))  # the gamut's nearest point is its green corner


async def test_color_is_sent_as_is_when_the_light_reports_no_gamut(hass, bridge):
    await lamp(hass, bridge, xy=(0.4, 0.4))

    await call(hass, "set_attributes", {"entity_id": "light.lamp", "xy_color": [0.1, 0.9]})

    assert bridge.puts == [("light/light-1", color((0.1, 0.9)))]
