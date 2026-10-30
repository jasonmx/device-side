"""Schema for raise_brightness: its limit's range."""

import probatio
import pytest

from custom_components.device_side.actions.raise_brightness import RaiseBrightness


@pytest.mark.parametrize("limit", [1, 100])
def test_the_limit_takes_its_range(limit):
    assert RaiseBrightness.schema()({"entity_id": "light.a", "limit": limit})["limit"] == limit


def test_a_limit_outside_it_is_refused():
    # 0 % would turn the light off, which raising never does.
    with pytest.raises(probatio.Invalid):
        RaiseBrightness.schema()({"entity_id": "light.a", "limit": 0})
