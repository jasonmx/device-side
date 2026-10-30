"""Schema for raise_hue: a cycle has no end, so no limit."""

import probatio
import pytest

from custom_components.device_side.actions.raise_hue import RaiseHue


def test_there_is_no_limit():
    with pytest.raises(probatio.Invalid):
        RaiseHue.schema()({"entity_id": "light.a", "limit": 50})
