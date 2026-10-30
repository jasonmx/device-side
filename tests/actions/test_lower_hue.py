"""Schema for lower_hue: a cycle has no end, so no limit."""

import probatio
import pytest

from custom_components.device_side.actions.lower_hue import LowerHue


def test_there_is_no_limit():
    with pytest.raises(probatio.Invalid):
        LowerHue.schema()({"entity_id": "light.a", "limit": 50})
