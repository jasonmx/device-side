"""What the raise and lower actions share: sweep_time, the parse, and dropping the attribute a target lacks."""

import probatio
import pytest
from homeassistant.core import ServiceCall

from custom_components.device_side.actions import discover
from custom_components.device_side.actions.ramp import Ramp, RampRequest

RAMPS = [action for action in discover() if issubclass(action, Ramp)]


def test_six_actions_one_per_attribute_and_direction():
    assert sorted((action.attribute, action.up) for action in RAMPS) == sorted(
        (attribute, up) for attribute in ("brightness", "saturation", "hue") for up in (True, False)
    )


@pytest.mark.parametrize("action", RAMPS, ids=lambda action: action.key)
def test_sweep_time_defaults_to_5_s_and_must_be_positive(action):
    assert action.schema()({"entity_id": "light.a"})["sweep_time"] == 5.0
    with pytest.raises(probatio.Invalid):
        action.schema()({"entity_id": "light.a", "sweep_time": 0})


@pytest.mark.parametrize("action", RAMPS, ids=lambda action: action.key)
@pytest.mark.parametrize(
    "data",
    [
        pytest.param({"brightness": "up"}, id="direction"),
        pytest.param({"color_temp_limit": 4000}, id="color_temperature"),
    ],
)
def test_no_direction_or_other_attribute_is_a_field(action, data):
    # The action names the attribute and direction. Every halt of a Hue bulb's color temperature fade jumps visibly,
    # so no integration moves it.
    with pytest.raises(probatio.Invalid):
        action.schema()({"entity_id": "light.a", **data})


@pytest.mark.parametrize("action", RAMPS, ids=lambda action: action.key)
def test_parse_carries_the_actions_attribute_and_direction(hass, action):
    data = action.schema()({"entity_id": "light.a", "sweep_time": 2})

    request = action.parse(hass, ServiceCall(hass, "device_side", action.key, data))

    assert request == RampRequest(action.attribute, action.up, 2.0, data.get("limit"))


@pytest.mark.parametrize(("up", "limit", "end"), [(True, None, 100.0), (False, None, 0.0), (False, 30.0, 30.0)])
def test_the_end_is_the_limit_or_the_range_end(up, limit, end):
    assert RampRequest("brightness", up, limit=limit).end() == end


def test_a_lacked_attribute_is_dropped_and_leaves_nothing_to_do():
    request = RampRequest("saturation", True)

    assert request.fields_present() == {"saturation"}
    assert request.without(frozenset({"brightness"})) == request
    dropped = request.without(frozenset({"saturation"}))
    assert dropped.fields_present() == frozenset()
    assert dropped.nothing_to_do()
    assert not request.nothing_to_do()
