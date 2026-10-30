"""Zigbee2MQTT lower_saturation: the bulb fades saturation down to the limit at the current hue (fade)."""

from typing import ClassVar

from .fade import Z2MRamp, ramp_scope
from ...core.scope import AdapterScope
from ...core.transition import SATURATION


class Z2MLowerSaturation(Z2MRamp):
    action: ClassVar[str] = "lower_saturation"
    scope: ClassVar[AdapterScope] = ramp_scope(SATURATION)
