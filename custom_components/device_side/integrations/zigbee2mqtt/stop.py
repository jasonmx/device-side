"""Zigbee2MQTT stop: halt the bulb's fades and hue cycle, remember where they halted, and bring HA's color in line."""

from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import topic
from .bridge import publish
from .move import hue_moves, lights_of, read_back_key, transition_cache
from .xy_writeback import DELAY_S, write_back_xy
from ...core.adapter import Adapter
from ...core.dispatcher import EMPTY_GROUP
from ...core.models import EntityResult, Request, Status, Target
from ...core.runtime import get_runtime
from ...core.scope import AdapterScope
from ...core.transition import BRIGHTNESS, SATURATION, hs_color, light_brightness, lit

# Z2M's saturation_move: stop halts only the saturation attribute, and the xy fade our saturation move runs carries on.
_STOP_MOVE_STEP = {
    "command": {
        "cluster": "lightingColorCtrl",
        "command": "stopMoveStep",
        "payload": {"optionsMask": 0, "optionsOverride": 0},
    }
}


class Z2MStop(Adapter[Request]):
    """Send brightness_move: stop to the light or group, with hue_move: stop where a hue move of ours cycles and a raw
    stopMoveStep where a saturation move of ours fades, and record the predicted values as where it halted.

    Each stop is its own publish, the color ones first: Z2M reads the light back after a brightness stop before it
    sends the next key of the same message. Z2M's read-back puts HA right for brightness; after a color stop, HA's color
    is brought in line (xy_writeback). A light or group with nothing lit (off, and no soft off of ours fading it) is
    unchanged with off and nothing is sent. Color temperature isn't stopped: our moves never fade it.
    """

    action: ClassVar[str] = "stop"
    integration: ClassVar[str] = "zigbee2mqtt"
    scope: ClassVar[AdapterScope] = AdapterScope(experimental=True, domains=frozenset({"light"}), native_groups=True)

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if topic(target, "set") is None:
            return "not_addressable"
        return None

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        cache = transition_cache(hass)
        cycling = hue_moves(hass)

        async def send(target: Target) -> EntityResult:
            if not (lights := await lights_of(hass, target)):
                return self.result(target, Status.UNSUPPORTED, detail=EMPTY_GROUP)
            if not (halting := lit(cache, lights)):
                return self.result(target, Status.UNCHANGED, detail="off")
            # A halt is predicted only where a move of ours ran: elsewhere Z2M's read-back is right at once.
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
            hue = [light.entity_id for light in halting if light.entity_id in cycling]
            set_topic = topic(target, "set")
            async with cache.recording(
                (light_id, attribute) for attribute, values in halts.items() for light_id in values
            ):
                for attribute, values in halts.items():
                    for light_id, value in values.items():
                        cache.stopped(light_id, attribute, value)
                if hue:
                    await publish(hass, set_topic, {"hue_move": "stop"})
                if halts[SATURATION]:
                    await publish(hass, set_topic, _STOP_MOVE_STEP)
                await publish(hass, set_topic, {"brightness_move": "stop"})
            cycling.difference_update(hue)

            async def bring_color_in_line() -> None:
                # A raw stopMoveStep publishes nothing, so Z2M has no read-back of its own.
                await write_back_xy(hass, target, silent=bool(halts[SATURATION]))

            # Replaces the end read-back of the move this halts.
            color_halted = hue or halts[SATURATION]
            get_runtime(hass).schedule(
                hass, read_back_key(target), [(DELAY_S, bring_color_in_line)] if color_halted else []
            )
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)
