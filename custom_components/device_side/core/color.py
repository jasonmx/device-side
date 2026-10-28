"""Colors shared so every integration reads and writes them alike: a requested color as xy, and the color entries
of a get_attributes row.

A light reports color in one native form; the row carries it with the other two of `rgb_color`, `hs_color` and
`xy_color` derived from it, as core's light state does.
"""

from homeassistant.util.color import (
    color_hs_to_RGB,
    color_hs_to_xy,
    color_RGB_to_hs,
    color_RGB_to_xy,
    color_xy_to_hs,
    color_xy_to_RGB,
)

from .models import LightFields


def color_xy(fields: LightFields) -> tuple[float, float] | None:
    """The requested color as CIE xy: rgb_color first, then hs_color, then xy_color, as hue_dimmer chose."""
    if fields.rgb_color is not None:
        return color_RGB_to_xy(*fields.rgb_color)
    if fields.hs_color is not None:
        return color_hs_to_xy(*fields.hs_color)
    if fields.xy_color is not None:
        return (float(fields.xy_color[0]), float(fields.xy_color[1]))
    return None


def xy_row(x: float, y: float) -> dict:
    return {"xy_color": [x, y], "rgb_color": list(color_xy_to_RGB(x, y)), "hs_color": list(color_xy_to_hs(x, y))}


def hs_row(h: float, s: float) -> dict:
    return {"hs_color": [h, s], "rgb_color": list(color_hs_to_RGB(h, s)), "xy_color": list(color_hs_to_xy(h, s))}


def rgb_row(r: int, g: int, b: int) -> dict:
    rgb = (r, g, b)
    return {"rgb_color": list(rgb), "hs_color": list(color_RGB_to_hs(*rgb)), "xy_color": list(color_RGB_to_xy(*rgb))}
