"""Schema for raise_saturation: its limit's range."""

import probatio
import pytest

from custom_components.device_side.actions.raise_saturation import RaiseSaturation


@pytest.mark.parametrize("limit", [0, 100])
def test_the_limit_takes_its_range(limit):
    assert RaiseSaturation.schema()({"entity_id": "light.a", "limit": limit})["limit"] == limit


def test_a_limit_outside_it_is_refused():
    with pytest.raises(probatio.Invalid):
        RaiseSaturation.schema()({"entity_id": "light.a", "limit": 101})
