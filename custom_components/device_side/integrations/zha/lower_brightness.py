"""ZHA lower_brightness: the bulb fades brightness down to the limit, or to a soft off at 0 % (fade)."""

from typing import ClassVar

from .fade import ZHARamp, ramp_scope
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS


class ZHALowerBrightness(ZHARamp):
    action: ClassVar[str] = "lower_brightness"
    scope: ClassVar[AdapterScope] = ramp_scope(BRIGHTNESS)
