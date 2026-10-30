"""ZHA raise_saturation: the bulb fades saturation up to the limit at the current hue (fade)."""

from typing import ClassVar

from .fade import ZHARamp, ramp_scope
from ...core.scope import AdapterScope
from ...core.transition import SATURATION


class ZHARaiseSaturation(ZHARamp):
    action: ClassVar[str] = "raise_saturation"
    scope: ClassVar[AdapterScope] = ramp_scope(SATURATION)
