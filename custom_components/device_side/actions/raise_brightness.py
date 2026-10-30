from typing import ClassVar

from .ramp import BRIGHTNESS, Ramp, limit_field


class RaiseBrightness(Ramp):
    """Raise brightness toward 100 % or the limit; the light turns on."""

    key: ClassVar[str] = "raise_brightness"
    attribute: ClassVar[str] = BRIGHTNESS
    up: ClassVar[bool] = True
    fields: ClassVar[dict] = {**Ramp.fields, **limit_field(1, 100)}


ACTION = RaiseBrightness
