"""Zigbee2MQTT lower_hue: the bulb cycles hue down the wheel until a stop (fade)."""

from typing import ClassVar

from .fade import Z2MRamp, ramp_scope
from ...actions.ramp import HUE
from ...core.scope import AdapterScope


class Z2MLowerHue(Z2MRamp):
    action: ClassVar[str] = "lower_hue"
    scope: ClassVar[AdapterScope] = ramp_scope(HUE)
