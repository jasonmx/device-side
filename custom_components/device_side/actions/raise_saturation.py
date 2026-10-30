from typing import ClassVar

from .ramp import SATURATION, Ramp, limit_field


class RaiseSaturation(Ramp):
    """Raise saturation toward 100 % or the limit: a richer color."""

    key: ClassVar[str] = "raise_saturation"
    attribute: ClassVar[str] = SATURATION
    up: ClassVar[bool] = True
    fields: ClassVar[dict] = {**Ramp.fields, **limit_field(0, 100)}


ACTION = RaiseSaturation
