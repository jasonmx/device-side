from typing import ClassVar

from .ramp import HUE, Ramp


class RaiseHue(Ramp):
    """Cycle hue up the wheel, red to yellow to green, until a stop."""

    key: ClassVar[str] = "raise_hue"
    attribute: ClassVar[str] = HUE
    up: ClassVar[bool] = True


ACTION = RaiseHue
