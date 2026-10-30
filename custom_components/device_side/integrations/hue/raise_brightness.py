"""Hue raise_brightness: the bridge fades brightness up to the limit, turning the light on (fade)."""

from typing import ClassVar

from .fade import HueBrightnessFade


class HueRaiseBrightness(HueBrightnessFade):
    action: ClassVar[str] = "raise_brightness"
