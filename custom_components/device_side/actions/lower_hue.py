from typing import ClassVar

from .ramp import HUE, Ramp


class LowerHue(Ramp):
    """Cycle hue down the wheel, red to magenta to blue, until a stop."""

    key: ClassVar[str] = "lower_hue"
    attribute: ClassVar[str] = HUE
    up: ClassVar[bool] = False


ACTION = LowerHue
