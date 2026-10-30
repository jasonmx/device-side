"""Zigbee2MQTT raise_brightness: the bulb fades brightness up to the limit, turning the light on (fade)."""

from typing import ClassVar

from .fade import Z2MRamp, ramp_scope
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS


class Z2MRaiseBrightness(Z2MRamp):
    action: ClassVar[str] = "raise_brightness"
    scope: ClassVar[AdapterScope] = ramp_scope(BRIGHTNESS)
