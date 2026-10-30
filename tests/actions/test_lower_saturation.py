"""Schema for lower_saturation: its limit's range."""

import probatio
import pytest

from custom_components.device_side.actions.lower_saturation import LowerSaturation


@pytest.mark.parametrize("limit", [0, 100])
def test_the_limit_takes_its_range(limit):
    assert LowerSaturation.schema()({"entity_id": "light.a", "limit": limit})["limit"] == limit


def test_a_limit_outside_it_is_refused():
    with pytest.raises(probatio.Invalid):
        LowerSaturation.schema()({"entity_id": "light.a", "limit": -1})
