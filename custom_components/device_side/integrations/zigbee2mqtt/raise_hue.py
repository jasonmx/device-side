"""Zigbee2MQTT raise_hue: the bulb cycles hue up the wheel until a stop (fade)."""

from typing import ClassVar

from .fade import Z2MRamp, ramp_scope
from ...actions.ramp import HUE
from ...core.scope import AdapterScope


class Z2MRaiseHue(Z2MRamp):
    action: ClassVar[str] = "raise_hue"
    scope: ClassVar[AdapterScope] = ramp_scope(HUE)
