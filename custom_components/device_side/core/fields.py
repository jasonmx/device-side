"""The fields a target can't take at all, read from its state as light.turn_on's filter_turn_on_params reads them."""

from homeassistant.components.light import (
    ATTR_SUPPORTED_COLOR_MODES,
    LightEntityFeature,
    brightness_supported,
    color_supported,
    color_temp_supported,
)
from homeassistant.const import ATTR_SUPPORTED_FEATURES

from .models import Request, Target

# Each action's fields by the light capability they need. Core converts between color forms before it filters, so a
# color is lacked only without any color mode, and a color temperature only without that or a color mode.
BRIGHTNESS = frozenset({"brightness", "min_brightness", "max_brightness"})
COLOR_TEMP = frozenset({"color_temp_kelvin"})
COLOR = frozenset({"hs_color", "rgb_color", "xy_color", "hue", "saturation"})
TRANSITION = frozenset({"transition"})


def lacking(target: Target, request: Request) -> frozenset[str]:
    """The request's fields the target lacks. A switch, or the switch a switch_as_x light drives, lacks them all.

    A light whose state doesn't list its color modes or features lacks nothing by that attribute: only a state that
    says the light can't take a field drops it.
    """
    present = request.fields_present()
    if not present or target.domain != "light":
        return present
    attributes = target.state.attributes if target.state is not None else {}
    lacked: set[str] = set()
    if (modes := attributes.get(ATTR_SUPPORTED_COLOR_MODES)) is not None:
        if not brightness_supported(modes):
            lacked |= BRIGHTNESS
        if not color_supported(modes):
            lacked |= COLOR
            if not color_temp_supported(modes):
                lacked |= COLOR_TEMP
    features = attributes.get(ATTR_SUPPORTED_FEATURES)
    if features is not None and not features & LightEntityFeature.TRANSITION:
        lacked |= TRANSITION
    return present & lacked
