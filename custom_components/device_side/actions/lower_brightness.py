from typing import ClassVar

from .ramp import BRIGHTNESS, Ramp, limit_field


class LowerBrightness(Ramp):
    """Lower brightness toward 0 % or the limit; at 0 % the light turns off."""

    key: ClassVar[str] = "lower_brightness"
    attribute: ClassVar[str] = BRIGHTNESS
    up: ClassVar[bool] = False
    fields: ClassVar[dict] = {**Ramp.fields, **limit_field(0, 99)}


ACTION = LowerBrightness
