"""Hue set_scene: the scene's settings written light by light, which needs no recall and so turns nothing on."""

import logging
from typing import ClassVar

from aiohue.v2.models.resource import ResourceTypes
from aiohue.v2.models.scene import Scene
from homeassistant.core import HomeAssistant

from .bridge import bridge_api, resource_id, write_light
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope

_LOGGER = logging.getLogger(__name__)


def scene_light_writes(scene: Scene) -> list[tuple[str, dict]]:
    """Each light action of the scene as write_light arguments.

    The Hue API has no recall that leaves lights off, so the scene is replayed as plain light writes. `on: true` is
    dropped so no light turns on; `on: false` is sent, as a recall would. Gradients, effects and dynamics are not
    written, so a dynamic scene sets its first frame.
    """
    writes = []
    for scene_action in scene.actions:
        if scene_action.target.rtype != ResourceTypes.LIGHT:
            continue
        action = scene_action.action
        write: dict = {}
        if action.on is not None and action.on.on is False:
            write["on"] = False
        if action.dimming is not None:
            write["brightness"] = action.dimming.brightness
        if action.color is not None:
            write["color_xy"] = (action.color.xy.x, action.color.xy.y)
        if action.color_temperature is not None and action.color_temperature.mirek is not None:
            write["color_temp_mirek"] = action.color_temperature.mirek
        if write:
            writes.append((scene_action.target.rid, write))
    return writes


class HueSetScene(Adapter[Request]):
    """Read the scene from aiohue's live cache on every call, so edits made in the Hue app apply, then write it.

    One failing light does not stop the others: the result is sent with detail some_lights_failed, or rejected if
    every light failed. All-Day (smart) scenes have no fixed settings to write and are unsupported.
    """

    action: ClassVar[str] = "set_scene"
    integration: ClassVar[str] = "hue"
    scope: ClassVar[AdapterScope] = AdapterScope(experimental=True, domains=frozenset({"scene"}))

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if bridge_api(target) is None:
            return "bridge_v1"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            api = bridge_api(target)
            scene_id = resource_id(target)
            if api.scenes.smart_scene.get(scene_id) is not None:
                return self.result(target, Status.UNSUPPORTED, detail="smart_scene")
            if (scene := api.scenes.scene.get(scene_id)) is None:
                return self.result(target, Status.REJECTED, detail="scene_not_found")
            if not (writes := scene_light_writes(scene)):
                return self.result(target, Status.CONFIRMED, detail="nothing_to_set")

            failed = 0
            for light_id, write in writes:
                try:
                    await write_light(api, light_id, **write)
                except Exception as err:  # noqa: BLE001 - one light's failure must not stop the rest of the scene
                    failed += 1
                    _LOGGER.warning("set_scene %s: write to light %s failed: %s", target.entity_id, light_id, err)
            if failed == len(writes):
                return self.result(target, Status.REJECTED, detail="error")
            return self.result(target, Status.SENT, detail="some_lights_failed" if failed else None)

        return await self.gather(hass, targets, send)
