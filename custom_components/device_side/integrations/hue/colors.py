"""Light fields between HA's terms and the Hue API's: brightness 0-255 and percent, kelvin and mirek, colors and xy."""

from typing import TYPE_CHECKING

from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy, color_temperature_kelvin_to_mired

from ...core.models import LightFields

if TYPE_CHECKING:
    from aiohue.v2.models.light import Light


def to_percent(brightness: float) -> float:
    """HA's 0-255 brightness as Hue's percent, as core's hue integration converts it."""
    return brightness / 255 * 100


def from_percent(percent: float) -> int:
    """Hue's percent brightness as HA's 0-255, as core's hue integration reports it."""
    return round(percent / 100 * 255)


def color_xy(fields: LightFields) -> tuple[float, float] | None:
    """The requested color as CIE xy, whichever of rgb_color, hs_color and xy_color named it (the schema allows one)."""
    if fields.rgb_color is not None:
        return color_RGB_to_xy(*fields.rgb_color)
    if fields.hs_color is not None:
        return color_hs_to_xy(*fields.hs_color)
    if fields.xy_color is not None:
        return (float(fields.xy_color[0]), float(fields.xy_color[1]))
    return None


def mirek(light: Light, kelvin: float) -> int | None:
    """The kelvin as mirek within the light's own range, or None for a light without color temperature."""
    if (feature := light.color_temperature) is None:
        return None
    schema = feature.mirek_schema
    return min(max(color_temperature_kelvin_to_mired(kelvin), schema.mirek_minimum), schema.mirek_maximum)
