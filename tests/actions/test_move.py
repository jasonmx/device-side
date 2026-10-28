"""Schema for move."""

import probatio
import pytest

from custom_components.device_side.actions.move import Move


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({"color_temp": "warmer"}, id="direction"),
        pytest.param({"brightness": "up", "color_temp_limit": 4000}, id="limit"),
    ],
)
def test_color_temperature_is_not_a_move_field(data):
    # Every halt of a Hue bulb's color temperature fade jumps visibly, so no integration moves it.
    with pytest.raises(probatio.Invalid):
        Move.schema()({"entity_id": "light.a", **data})
