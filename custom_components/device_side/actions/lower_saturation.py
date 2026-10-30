from typing import ClassVar

from .ramp import SATURATION, Ramp, limit_field


class LowerSaturation(Ramp):
    """Lower saturation toward 0 % or the limit: paler, toward white."""

    key: ClassVar[str] = "lower_saturation"
    attribute: ClassVar[str] = SATURATION
    up: ClassVar[bool] = False
    fields: ClassVar[dict] = {**Ramp.fields, **limit_field(0, 100)}


ACTION = LowerSaturation
