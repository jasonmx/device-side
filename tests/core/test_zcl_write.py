"""set_attributes fields as neutral ZCL MoveTo commands, shared by the Zigbee adapters."""

import pytest
from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy, color_temperature_to_hs, color_xy_to_hs

from custom_components.device_side.actions.set_attributes import SetAttributesRequest
from custom_components.device_side.core.models import LightFields
from custom_components.device_side.core.zcl_write import (
    MoveToColor,
    MoveToColorTemp,
    MoveToHueAndSaturation,
    MoveToLevel,
    commands,
    wants_level,
)

ONOFF = {"supported_color_modes": ["onoff"]}
DIMMABLE = {"supported_color_modes": ["brightness"]}
CT = {"supported_color_modes": ["color_temp"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535}
COLOR = {**CT, "supported_color_modes": ["color_temp", "xy"]}
HS = {"supported_color_modes": ["hs"]}
_OWN = ("brightness", "min_brightness", "max_brightness")


def request(**data) -> SetAttributesRequest:
    light = LightFields.from_data({name: value for name, value in data.items() if name not in _OWN})
    return SetAttributesRequest(light=light, **{name: data[name] for name in _OWN if name in data})


def build(data: dict, attributes: dict, current_level: int | None = None):
    return commands(request(**data), set(attributes.get("supported_color_modes", ())), attributes, current_level)


@pytest.mark.parametrize(
    ("data", "attributes", "expected"),
    [
        pytest.param({"brightness": 40}, DIMMABLE, [MoveToLevel(102)], id="brightness"),
        pytest.param({"brightness": 0}, DIMMABLE, [MoveToLevel(1)], id="brightness_0_is_the_lowest_level"),
        pytest.param({"brightness": 100}, DIMMABLE, [MoveToLevel(254)], id="brightness_100"),
        pytest.param({"color_temp_kelvin": 2700}, CT, [MoveToColorTemp(370)], id="ct"),
        pytest.param({"color_temp_kelvin": 1000}, CT, [MoveToColorTemp(454)], id="ct_clamped_warm"),
        pytest.param({"color_temp_kelvin": 9000}, CT, [MoveToColorTemp(153)], id="ct_clamped_cool"),
        pytest.param(
            {"color_temp_kelvin": 9000},
            {"supported_color_modes": ["color_temp"]},
            [MoveToColorTemp(111)],
            id="ct_no_range",
        ),
        pytest.param(
            {"brightness": 40, "color_temp_kelvin": 2700},
            CT,
            [MoveToLevel(102), MoveToColorTemp(370)],
            id="brightness_and_ct",
        ),
        pytest.param({"xy_color": (0.369, 0.445)}, COLOR, [MoveToColor(0.369, 0.445)], id="xy"),
        pytest.param({"hs_color": (30, 80)}, COLOR, [MoveToColor(*color_hs_to_xy(30, 80))], id="hs_on_xy_bulb"),
        pytest.param(
            {"rgb_color": (255, 128, 0)}, COLOR, [MoveToColor(*color_RGB_to_xy(255, 128, 0))], id="rgb_on_xy_bulb"
        ),
        pytest.param(
            {"xy_color": (0.369, 0.445), "color_temp_kelvin": 2700},
            COLOR,
            [MoveToColor(0.369, 0.445)],
            id="color_wins_over_ct",
        ),
        pytest.param(
            {"color_temp_kelvin": 2700},
            {"supported_color_modes": ["xy"]},
            [MoveToColor(*color_hs_to_xy(*color_temperature_to_hs(2700)))],
            id="ct_as_a_color_without_ct_mode",
        ),
    ],
)
def test_fields_become_commands(data, attributes, expected):
    assert build(data, attributes) == (expected, False)


def test_color_on_an_hs_only_light_is_hue_and_saturation():
    hue, saturation = color_xy_to_hs(0.369, 0.445)

    assert build({"xy_color": (0.369, 0.445)}, HS) == (
        [MoveToHueAndSaturation(round(hue * 254 / 360), round(saturation * 254 / 100))],
        False,
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param({"min_brightness": 60}, [MoveToLevel(152)], id="min_raises"),
        pytest.param({"max_brightness": 30}, [MoveToLevel(76)], id="max_lowers"),
        pytest.param({"min_brightness": 20, "max_brightness": 80}, [], id="within_limits"),
        pytest.param({"min_brightness": 20, "brightness": 10}, [MoveToLevel(25)], id="brightness_wins"),
    ],
)
def test_limits_clamp_the_current_level(data, expected):
    assert build(data, DIMMABLE, current_level=127) == (expected, False)


def test_a_field_the_light_cant_take_is_dropped():
    assert build({"brightness": 40, "hs_color": (30, 80)}, CT) == ([MoveToLevel(102)], True)


@pytest.mark.parametrize(
    ("attributes", "data"),
    [
        pytest.param(ONOFF, {"brightness": 40, "color_temp_kelvin": 2700}, id="onoff_light"),
        pytest.param(ONOFF, {"min_brightness": 40}, id="onoff_light_limits"),
        pytest.param(DIMMABLE, {"rgb_color": (255, 0, 0), "color_temp_kelvin": 2700}, id="every_field_dropped"),
        pytest.param({}, {"brightness": 40, "rgb_color": (255, 0, 0), "color_temp_kelvin": 2700}, id="no_modes"),
    ],
)
def test_a_light_that_takes_no_field_gets_no_command(attributes, data):
    assert build(data, attributes) == ([], True)


@pytest.mark.parametrize(
    ("data", "modes", "expected"),
    [
        pytest.param({"min_brightness": 60}, {"brightness"}, True, id="limits_alone"),
        pytest.param({"min_brightness": 60, "brightness": 10}, {"brightness"}, False, id="with_brightness"),
        pytest.param({"max_brightness": 60}, {"onoff"}, False, id="onoff_light"),
        pytest.param({"color_temp_kelvin": 2700}, {"color_temp"}, False, id="no_limits"),
    ],
)
def test_wants_level(data, modes, expected):
    assert wants_level(request(**data), modes) is expected
