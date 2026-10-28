"""The color entries of a get_attributes row, shared so every integration reports a color alike.

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


def xy_row(x: float, y: float) -> dict:
    return {"xy_color": [x, y], "rgb_color": list(color_xy_to_RGB(x, y)), "hs_color": list(color_xy_to_hs(x, y))}


def hs_row(h: float, s: float) -> dict:
    return {"hs_color": [h, s], "rgb_color": list(color_hs_to_RGB(h, s)), "xy_color": list(color_hs_to_xy(h, s))}


def rgb_row(r: int, g: int, b: int) -> dict:
    rgb = (r, g, b)
    return {"rgb_color": list(rgb), "hs_color": list(color_RGB_to_hs(*rgb)), "xy_color": list(color_RGB_to_xy(*rgb))}
