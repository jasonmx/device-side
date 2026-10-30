"""ZHA raise_hue: the bulb cycles hue up the wheel until a stop (fade)."""

from typing import ClassVar

from .fade import ZHARamp, ramp_scope
from ...actions.ramp import HUE
from ...core.scope import AdapterScope


class ZHARaiseHue(ZHARamp):
    action: ClassVar[str] = "raise_hue"
    scope: ClassVar[AdapterScope] = ramp_scope(HUE)
