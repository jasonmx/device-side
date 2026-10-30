"""Hue lower_brightness: the bridge fades brightness down to the limit, or soft off at 0 % (fade)."""

from typing import ClassVar

from .fade import HueBrightnessFade


class HueLowerBrightness(HueBrightnessFade):
    action: ClassVar[str] = "lower_brightness"
