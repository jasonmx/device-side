"""Light fields between HA's terms and the Hue API's: kelvin and mirek, and a light's gamut."""

from typing import TYPE_CHECKING

from homeassistant.util.color import (
    GamutType,
    XYPoint,
    check_point_in_lamps_reach,
    check_valid_gamut,
    color_temperature_kelvin_to_mired,
    get_closest_point_to_point,
)

if TYPE_CHECKING:
    from aiohue.v2.models.light import Light


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
