"""Hue set_attributes: one write per light, which the bridge stores whether the light is on or off."""

from typing import TYPE_CHECKING, ClassVar

from homeassistant.core import HomeAssistant

from . import colors
from .bridge import bridge_api, resource_id, write_light
from ...actions.set_attributes import SetAttributesRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope

if TYPE_CHECKING:
    from aiohue.v2.models.light import Light

# Below this a clamp changes nothing: the dimmest step a Hue light makes is 0.4 %.
_BRIGHTNESS_EPSILON = 0.1


def _clamp(current: float, low: float | None, high: float | None) -> float | None:
    """The brightness min/max_brightness move the current one to, or None when it is already within them."""
    clamped = current
    if low is not None:
        clamped = max(low, clamped)
    if high is not None:
        clamped = min(high, clamped)
    return clamped if abs(clamped - current) > _BRIGHTNESS_EPSILON else None


def _write_for(light: Light, request: SetAttributesRequest) -> tuple[dict, bool]:
    """The write_light arguments for this light, and whether it had to drop a field it cannot take."""
    fields = request.light
    write: dict = {}
    dropped = False
    if request.brightness is not None or request.min_brightness is not None or request.max_brightness is not None:
        if light.dimming is None:
            dropped = True
        elif request.brightness is not None:
            write["brightness"] = request.brightness
        elif (clamped := _clamp(light.dimming.brightness, request.min_brightness, request.max_brightness)) is not None:
            write["brightness"] = clamped
    if fields.color_temp_kelvin is not None:
        if (mirek := colors.mirek(light, fields.color_temp_kelvin)) is None:
            dropped = True
        else:
            write["color_temp_mirek"] = mirek
    if (xy := colors.color_xy(fields)) is not None:
        if light.color is None:
            dropped = True
        else:
            write["color_xy"] = xy
    return write, dropped


class HueSetAttributes(Adapter[SetAttributesRequest]):
    """Write the requested attributes to each light; the dispatcher expands a room or zone into its lights.

    A grouped_light write does not reach the lights that are off, so a room is written light by light. A field the
    light cannot take (color on a white bulb) is dropped and the result says so; a light that can take none of the
    fields is unsupported. min/max_brightness clamp the brightness the bridge last stored, so they work while off.
    """

    action: ClassVar[str] = "set_attributes"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        fields=frozenset(
            {"brightness", "color_temp_kelvin", "hs_color", "rgb_color", "xy_color", "min_brightness", "max_brightness"}
        ),
    )

    def supports(self, hass: HomeAssistant, request: SetAttributesRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if bridge_api(target) is None:
            return "bridge_v1"
        return None

    async def execute(
        self, hass: HomeAssistant, request: SetAttributesRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            if (light := api.lights.get(resource_id(target))) is None:
                return self.result(target, Status.REJECTED, detail="not_on_bridge")
            write, dropped = _write_for(light, request)
            if not write:
                if dropped:
                    return self.result(target, Status.UNSUPPORTED, detail="fields_not_supported")
                return self.result(target, Status.UNCHANGED, detail="within_limits")
            await write_light(api, light.id, **write)
            return self.result(target, Status.SENT, detail="fields_dropped" if dropped else None)

        return await self.gather(hass, targets, send)
