"""Schema and parse for turn_on_for / turn_off_for."""

import probatio
import pytest
from homeassistant.core import ServiceCall

from custom_components.device_side.core.models import LightFields
from custom_components.device_side.features.turn_off_for import TurnOffFor
from custom_components.device_side.features.turn_on_for import TurnOnFor


def _parse(hass, feature, data):
    return feature.parse(hass, ServiceCall(hass, "device_side", feature.key, feature.schema()(data)))


async def test_duration_accepts_seconds_and_selector_dict(hass):
    assert _parse(hass, TurnOnFor, {"entity_id": "light.a", "duration": 90}).duration_s == 90
    request = _parse(hass, TurnOffFor, {"entity_id": "light.a", "duration": {"minutes": 1, "milliseconds": 500}})
    assert request.duration_s == 60.5


async def test_light_fields_are_parsed_with_core_validators(hass):
    request = _parse(
        hass,
        TurnOnFor,
        {"entity_id": "light.a", "duration": 5, "brightness": 300, "hs_color": [30, 50], "transition": 2},
    )

    assert request.light == LightFields(brightness=255, hs_color=(30.0, 50.0), transition=2.0)
    assert request.fields_present() == {"brightness", "hs_color", "transition"}
    assert request.light.as_turn_on_data() == {"brightness": 255, "hs_color": (30.0, 50.0), "transition": 2.0}


def test_one_color_at_a_time():
    with pytest.raises(probatio.Invalid):
        TurnOnFor.schema()({"entity_id": "light.a", "duration": 5, "rgb_color": [1, 2, 3], "color_temp_kelvin": 3000})


def test_turn_off_for_takes_no_light_fields():
    with pytest.raises(probatio.Invalid):
        TurnOffFor.schema()({"entity_id": "light.a", "duration": 5, "brightness": 10})
