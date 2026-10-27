"""Light fields between HA's terms and the Hue API's: kelvin and mirek, colors and xy."""

from typing import TYPE_CHECKING

from homeassistant.util.color import (
    GamutType,
    XYPoint,
    check_point_in_lamps_reach,
    check_valid_gamut,
    color_hs_to_xy,
    color_RGB_to_xy,
    color_temperature_kelvin_to_mired,
    get_closest_point_to_point,
)

from ...core.models import LightFields

if TYPE_CHECKING:
    from aiohue.v2.models.light import Light


def color_xy(fields: LightFields) -> tuple[float, float] | None:
    """The requested color as CIE xy: rgb_color first, then hs_color, then xy_color, as hue_dimmer chose."""
    if fields.rgb_color is not None:
        return color_RGB_to_xy(*fields.rgb_color)
    if fields.hs_color is not None:
        return color_hs_to_xy(*fields.hs_color)
    if fields.xy_color is not None:
        return (float(fields.xy_color[0]), float(fields.xy_color[1]))
    return None


def clamp_to_gamut(light: Light, xy: tuple[float, float]) -> tuple[float, float]:
    """The xy, or the nearest point of the light's gamut if outside it; as is for a light with no usable gamut."""
    if light.color is None or (gamut := light.color.gamut) is None:
        return xy
    triangle = GamutType(
        XYPoint(gamut.red.x, gamut.red.y), XYPoint(gamut.green.x, gamut.green.y), XYPoint(gamut.blue.x, gamut.blue.y)
    )
    if not check_valid_gamut(triangle) or check_point_in_lamps_reach(xy, triangle):
        return xy
    return get_closest_point_to_point(xy, triangle)


def mirek(light: Light, kelvin: float) -> int | None:
    """The kelvin as mirek within the light's own range, or None for a light without color temperature."""
    if (feature := light.color_temperature) is None:
        return None
    schema = feature.mirek_schema
    return min(max(color_temperature_kelvin_to_mired(kelvin), schema.mirek_minimum), schema.mirek_maximum)
