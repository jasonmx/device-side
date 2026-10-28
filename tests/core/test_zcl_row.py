"""The get_attributes row from raw ZCL attributes, and a group's averaged row."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.util.color import color_hs_to_RGB, color_hs_to_xy, color_xy_to_hs, color_xy_to_RGB

from custom_components.device_side.core.zcl_row import average, zcl_row

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def timer(remaining_s: float) -> dict:
    ends_at = (NOW + timedelta(seconds=remaining_s)).isoformat()
    return {"turns": "off", "ends_at": ends_at, "remaining_s": remaining_s}


def xy_row(x: float, y: float) -> dict:
    return {"xy_color": [x, y], "rgb_color": list(color_xy_to_RGB(x, y)), "hs_color": list(color_xy_to_hs(x, y))}


@pytest.mark.parametrize(("level", "percent"), [(254, 100.0), (152, 59.8), (1, 0.4), (0, 0.0)])
def test_brightness_is_a_percent_of_current_level(level, percent):
    assert zcl_row({"currentLevel": level}, NOW) == {"brightness": percent}


def test_color_temp_mode_reports_kelvin_only():
    attributes = {"colorMode": 2, "colorTemperature": 250, "currentX": 24982, "currentY": 24866}

    assert zcl_row(attributes, NOW) == {"color_temp_kelvin": 4000}


def test_xy_mode_reports_xy_and_the_colors_derived_from_it():
    attributes = {"colorMode": 1, "colorTemperature": 153, "currentX": 19667, "currentY": 32722}

    assert zcl_row(attributes, NOW) == xy_row(0.3001, 0.4993)


def test_hs_mode_reports_hue_and_saturation_and_the_colors_derived_from_them():
    attributes = {"colorMode": 0, "currentHue": 127, "currentSaturation": 254, "currentX": 11233, "currentY": 26852}

    hs = (180.0, 100.0)
    assert zcl_row(attributes, NOW) == {
        "hs_color": list(hs), "rgb_color": list(color_hs_to_RGB(*hs)), "xy_color": list(color_hs_to_xy(*hs)),
    }


def test_hs_mode_without_hue_and_saturation_reports_xy():
    attributes = {"colorMode": 0, "currentX": 11233, "currentY": 26852}

    assert zcl_row(attributes, NOW) == xy_row(0.1714, 0.4097)


@pytest.mark.parametrize(
    "attributes",
    [
        {"colorMode": 2, "colorTemperature": 0},  # no valid color temperature
        {"colorMode": 2, "currentX": 1, "currentY": 1},  # color temperature not read
        {"colorMode": 1, "colorTemperature": 250},  # xy not read
        {"colorMode": 3, "currentX": 1, "currentY": 1},  # not a ColorMode value
        {"colorTemperature": 250},  # ColorMode not read
    ],
)
def test_no_color_without_the_active_modes_attributes(attributes):
    assert zcl_row(attributes, NOW) == {}


def test_running_timer_reports_on_time_in_seconds():
    assert zcl_row({"onOff": 1, "onTime": 270}, NOW) == {"timer": timer(27.0)}


@pytest.mark.parametrize(
    "attributes", [{"onOff": 1, "onTime": 0}, {"onOff": 0, "onTime": 0}, {"onOff": 0, "onTime": 5}]
)
def test_no_timer_unless_on_with_time_left(attributes):
    assert zcl_row(attributes, NOW) == {}


def test_average_of_brightness_color_temp_and_xy():
    rows = [
        {"brightness": 40.0, "color_temp_kelvin": 3000},
        {"brightness": 60.0, "color_temp_kelvin": 4001},
        {"brightness": 51.0, **xy_row(0.3, 0.5)},
        xy_row(0.2, 0.3),
    ]

    assert average(rows) == {"brightness": 50.3, "color_temp_kelvin": 3500, **xy_row(0.25, 0.4)}


def test_average_reports_the_longest_timer_when_every_row_has_one():
    assert average([{"timer": timer(5.0)}, {"timer": timer(12.5)}]) == {"timer": timer(12.5)}


def test_average_reports_no_timer_when_a_row_has_none():
    assert average([{"timer": timer(5.0)}, {"brightness": 10.0}]) == {"brightness": 10.0}


def test_average_of_no_rows_is_empty():
    assert average([]) == {}
