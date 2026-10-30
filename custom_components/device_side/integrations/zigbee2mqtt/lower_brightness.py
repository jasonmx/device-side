"""Zigbee2MQTT lower_brightness: the bulb fades brightness down to the limit, or soft off at 0 % (fade)."""

from typing import ClassVar

from .fade import Z2MRamp, ramp_scope
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS


class Z2MLowerBrightness(Z2MRamp):
    action: ClassVar[str] = "lower_brightness"
    scope: ClassVar[AdapterScope] = ramp_scope(BRIGHTNESS)
