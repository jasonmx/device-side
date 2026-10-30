"""Schema for lower_brightness: its limit's range."""

import probatio
import pytest

from custom_components.device_side.actions.lower_brightness import LowerBrightness


@pytest.mark.parametrize("limit", [0, 99])
def test_the_limit_takes_its_range(limit):
    assert LowerBrightness.schema()({"entity_id": "light.a", "limit": limit})["limit"] == limit


def test_a_limit_outside_it_is_refused():
    # Lowering to 100 % could never move; 0 % turns the light off.
    with pytest.raises(probatio.Invalid):
        LowerBrightness.schema()({"entity_id": "light.a", "limit": 100})
