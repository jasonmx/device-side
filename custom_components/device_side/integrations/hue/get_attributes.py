"""Hue get_attributes: brightness, color temperature and color from aiohue's cache of the bridge, lights off too."""

from collections.abc import Iterable
from statistics import mean
from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.util.color import color_temperature_mired_to_kelvin, color_xy_to_hs, color_xy_to_RGB

from . import colors
from .bridge import bridge_api, expand_group, resource_id
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope

if TYPE_CHECKING:
    from aiohue.v2.models.light import Light


def attributes(lights: Iterable[Light]) -> dict:
    """The lights' attributes under HA's names and units, each averaged over the lights that have it.

    Color temperature counts only lights in color temperature mode (mirek_valid), as core's hue integration does.
    """
    lights = list(lights)
    row: dict = {}
    if levels := [light.dimming.brightness for light in lights if light.dimming]:
        row["brightness"] = colors.from_percent(mean(levels))
    kelvins = [
        color_temperature_mired_to_kelvin(feature.mirek)
        for light in lights
        if (feature := light.color_temperature) and feature.mirek is not None and feature.mirek_valid
    ]
    if kelvins:
        row["color_temp_kelvin"] = round(mean(kelvins))
    if xys := [(light.color.xy.x, light.color.xy.y) for light in lights if light.color]:
        xy = (round(mean(x for x, _ in xys), 4), round(mean(y for _, y in xys), 4))
        row["xy_color"] = list(xy)
        row["rgb_color"] = list(color_xy_to_RGB(*xy))
        row["hs_color"] = list(color_xy_to_hs(*xy))
    return row


class HueGetAttributes(Adapter[Request]):
    """One row per light from aiohue's cache, which keeps what the bridge last reported after HA shows a light off.

    A room or zone gets its own row and one row per member light. The room row follows the bridge and core's hue
    integration: brightness is the grouped_light's (the average of the lights that are on), color temperature and
    color average the lights that are on. With every light off the bridge reports nothing useful, so the row
    averages all the room's lights.
    """

    action: ClassVar[str] = "get_attributes"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(experimental=True, confirmable=True, native_groups=True)

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if bridge_api(target) is None:
            return "bridge_v1"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        results = []
        for target in targets:
            api = bridge_api(target)
            if not target.is_group:
                if (light := api.lights.get(resource_id(target))) is None:
                    results.append(self.result(target, Status.REJECTED, detail="not_on_bridge"))
                else:
                    results.append(self.result(target, Status.CONFIRMED, data=attributes([light])))
                continue

            grouped = api.groups.grouped_light
            if not (lights := grouped.get_lights(resource_id(target))):
                results.append(self.result(target, Status.UNSUPPORTED, detail="empty_group"))
                continue
            on = [light for light in lights if light.on.on]
            row = attributes(on or lights)
            if on and (group := grouped.get(resource_id(target))) is not None and group.dimming is not None:
                row["brightness"] = colors.from_percent(group.dimming.brightness)
            results.append(self.result(target, Status.CONFIRMED, data=row))
            for member in expand_group(hass, target):
                if (light := api.lights.get(resource_id(member))) is not None:
                    results.append(
                        self.result(member, Status.CONFIRMED, data=attributes([light]), member_of=target.reported_id)
                    )
        return results
