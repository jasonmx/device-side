"""Hue get_attributes: brightness, color temperature and color from aiohue's cache of the bridge, lights off too."""

from collections.abc import Iterable
from statistics import mean
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.util.color import color_temperature_mired_to_kelvin

from .bridge import bridge_api, resource_id
from .move import light_mirek, lit
from .transition_cache import transition_cache
from ...core.adapter import Adapter
from ...core.color import xy_row
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, COLOR_TEMP, TransitionCache

if TYPE_CHECKING:
    from aiohue.v2.models.light import Light


def light_row(cache: TransitionCache, light: Light) -> dict:
    """One light's attributes, its brightness and color temperature predicted while a move runs (the bridge reports
    the end value)."""
    row = attributes([light])
    if light.dimming:
        row["brightness"] = round(cache.value(light.id, BRIGHTNESS, light.dimming.brightness), 1)
    if in_color_temp_mode(light):
        row["color_temp_kelvin"] = color_temperature_mired_to_kelvin(light_mirek(cache, light))
    return row


def in_color_temp_mode(light: Light) -> bool:
    return bool((feature := light.color_temperature) and feature.mirek is not None and feature.mirek_valid)


def attributes(lights: Iterable[Light]) -> dict:
    """The lights' attributes under HA's names, each averaged over the lights that have it.

    Brightness is Hue's percent, as hue_dimmer returned it, so a read can be written back with set_attributes.
    Color temperature counts only lights in color temperature mode (mirek_valid), as core's hue integration does.
    """
    lights = list(lights)
    row: dict = {}
    if levels := [light.dimming.brightness for light in lights if light.dimming]:
        row["brightness"] = round(mean(levels), 1)
    kelvins = [
        color_temperature_mired_to_kelvin(light.color_temperature.mirek)
        for light in lights
        if in_color_temp_mode(light)
    ]
    if kelvins:
        row["color_temp_kelvin"] = round(mean(kelvins))
    if xys := [(light.color.xy.x, light.color.xy.y) for light in lights if light.color]:
        row.update(xy_row(round(mean(x for x, _ in xys), 4), round(mean(y for _, y in xys), 4)))
    return row


class HueGetAttributes(Adapter[Request]):
    """One row per target from aiohue's cache, which keeps what the bridge last reported after HA shows a light off.

    A room or zone row follows the bridge and core's hue integration: brightness is the grouped_light's (the
    average of the lights that are on), color temperature and color average the lights that are on. With every
    light off the bridge reports nothing useful, so the row averages all the room's lights. Brightness reads through
    and color temperature read through the transition cache, so a light or room mid-move reports where it is, not the
    end value the bridge reports; a room then averages its lit lights' predictions.
    """

    action: ClassVar[str] = "get_attributes"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(experimental=True, confirmable=True, native_groups=True)

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if (api := bridge_api(target)) is None:
            return "bridge_v1"
        if target.is_group and not api.groups.grouped_light.get_lights(resource_id(target)):
            return "empty_group"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)
        results = []
        for target in targets:
            api = bridge_api(target)
            if not target.is_group:
                if (light := api.lights.get(resource_id(target))) is None:
                    results.append(self.result(target, Status.REJECTED, detail="not_on_bridge"))
                else:
                    results.append(self.result(target, Status.CONFIRMED, data=light_row(cache, light)))
                continue

            grouped = api.groups.grouped_light
            lights = grouped.get_lights(resource_id(target))
            on = [light for light in lights if light.on.on]
            row = attributes(on or lights)
            dimmable = [light for light in lights if light.dimming]
            if any(cache.tracks(light.id, BRIGHTNESS) for light in dimmable):
                # Mid-move the bridge reports end values; average the lit lights' predictions instead. A light
                # still moving counts as lit: a room moved up from all off is on before aiohue hears so.
                lights_lit = lit(cache, dimmable) or dimmable
                predicted = [cache.value(light.id, BRIGHTNESS, light.dimming.brightness) for light in lights_lit]
                row["brightness"] = round(mean(predicted), 1)
            elif on and (group := grouped.get(resource_id(target))) is not None and group.dimming is not None:
                row["brightness"] = round(group.dimming.brightness, 1)
            tunable = [light for light in lights if in_color_temp_mode(light)]
            if any(cache.tracks(light.id, COLOR_TEMP) for light in tunable):
                lights_lit = lit(cache, tunable) or tunable
                row["color_temp_kelvin"] = round(
                    mean(color_temperature_mired_to_kelvin(light_mirek(cache, light)) for light in lights_lit)
                )
            results.append(self.result(target, Status.CONFIRMED, data=row))
        return results
