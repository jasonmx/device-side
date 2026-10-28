"""ZHA stop: halt the bulb's fades and hue cycle with level Stop and StopMoveStep, remember where they halted, and
refresh HA."""

import asyncio
import logging
from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from . import zcl
from .addressing import unsupported_reason
from .move import has_color, hue_moves, job_key, refresh, send, transition_cache, units
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.runtime import get_runtime
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, SATURATION, TransitionCache, hs_color, light_brightness, lit

_LOGGER = logging.getLogger(__name__)

_LEVEL_STOP = (zcl.LEVEL_CLUSTER, zcl.STOP, {})
_STOP_MOVE_STEP = (zcl.COLOR_CLUSTER, zcl.STOP_MOVE_STEP, {"options_mask": 0, "options_override": 0})


class ZHAStop(Adapter[Request]):
    """Send level Stop to each lit light, with StopMoveStep where a saturation or hue move of ours runs, record the
    predicted values as where it halted, and refresh HA at once.

    Members from one ZHA group get one groupcast per command, as in move. The stop replaces the light's pending end
    refresh and soft off restore, so a halted soft off leaves the light on at the halted level, as on Hue. Raw commands
    leave ZHA's transitioning flag down, so the refresh reads the halted values. A light with nothing lit (off, and no
    soft off of ours fading it) is unchanged with off and nothing is sent to it.
    """

    action: ClassVar[str] = "stop"
    integration: ClassVar[str] = "zha"
    scope: ClassVar[AdapterScope] = AdapterScope(experimental=True, domains=frozenset({"light"}), max_concurrency=2)

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target)

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)
        runs = [self._unit(hass, request, cache, gid, lights) for gid, lights in units(hass, targets)]
        return [result for batch in await asyncio.gather(*runs) for result in batch]

    async def _unit(
        self, hass: HomeAssistant, request: Request, cache: TransitionCache, gid: int | None, lights: list[Target]
    ) -> list[EntityResult]:
        halting = lit(cache, lights)
        halting_ids = {light.entity_id for light in halting}
        off = [self.result(light, Status.UNCHANGED, detail="off") for light in lights if light not in halting]
        if not halting:
            return off
        # A halt is predicted only where a move of ours ran: elsewhere the refresh is right at once.
        halts = {
            BRIGHTNESS: {
                light.entity_id: light_brightness(cache, light)
                for light in halting
                if cache.tracks(light.entity_id, BRIGHTNESS)
            },
            SATURATION: {
                light.entity_id: cache.value(light.entity_id, SATURATION, (hs_color(light) or (0, 0))[1])
                for light in halting
                if cache.tracks(light.entity_id, SATURATION)
            },
        }
        cycling = hue_moves(hass)
        color = [
            light
            for light in halting
            if has_color(light) and (light.entity_id in halts[SATURATION] or light.entity_id in cycling)
        ]
        integration_limit, adapter_limit = self.limits(hass)
        try:
            async with integration_limit, adapter_limit:
                async with cache.recording(
                    (light_id, attribute) for attribute, values in halts.items() for light_id in values
                ):
                    for attribute, values in halts.items():
                        for light_id, value in values.items():
                            cache.stopped(light_id, attribute, value)
                    if color:
                        await send(hass, gid, color, _STOP_MOVE_STEP, request.context)
                    await send(hass, gid, halting, _LEVEL_STOP, request.context)
        except Unauthorized:
            return [*off, *(self.result(light, Status.REJECTED, detail="admin_required") for light in halting)]
        except Exception as err:  # noqa: BLE001 - as in gather(): one group's failure must not abort the room
            _LOGGER.warning("stop on zha failed for %s: %s", ", ".join(sorted(halting_ids)), err)
            return [*off, *(self.result(light, Status.REJECTED, detail="error") for light in halting)]
        cycling.difference_update(halting_ids)
        for light in halting:
            get_runtime(hass).schedule(hass, job_key(light), [])  # cancels the move's end refresh and restore
        await asyncio.gather(*(refresh(hass, light, request.context) for light in halting))
        return [*off, *(self.result(light, Status.SENT) for light in halting)]
