"""Zigbee2MQTT turn_on_for: optional light.turn_on for attributes, then mqtt.publish with on_time."""

import json
import logging
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import command_topic
from ...actions.turn_on_for import TurnOnForRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope, DurationLimits

_LOGGER = logging.getLogger(__name__)

# Zigbee OnWithTimedOff: on_time in tenths of a second (uint16), range 1-65534 tenths.
# 65534 tenths = 6553.4 s. The 50 ms floor from core/duration.py handles the effective minimum.
_TIMER_LIMITS = DurationLimits(min_s=0, max_s=6553.4)


class Z2MTurnOnFor(Adapter[TurnOnForRequest]):
    """Turn a Z2M light on for a duration using Zigbee2MQTT's on_time attribute.

    With fields: calls light.turn_on first (blocking) so HA's MQTT light entity applies brightness,
    color and transition through its own protocol, then publishes {"state":"ON","on_time":<seconds, 1dp>}
    to the device's command topic. Without fields: publishes only.

    Returns SENT (fire-and-forget via MQTT); the bridge forwards the command to the device.
    """

    action: ClassVar[str] = "turn_on_for"
    integration: ClassVar[str] = "zigbee2mqtt"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        # Zigbee plugs and switches rarely honor OnWithTimedOff, so switch stays out of scope until users ask.
        domains=frozenset({"light"}),
        duration=_TIMER_LIMITS,
        fields=frozenset({"brightness", "color_temp_kelvin", "hs_color", "rgb_color", "xy_color", "transition"}),
        capabilities=None,  # All Z2M devices that accept on_time; no hardware capability to restrict yet.
        confirmable=False,
        native_groups=True,  # Z2M group entities receive commands on <base>/<group ID>/set.
    )

    def supports(self, hass: HomeAssistant, request: TurnOnForRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if command_topic(target) is None:
            return "not_addressable"
        return None

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            topic = command_topic(target)
            if topic is None:  # defense in depth; supports() already refused this target
                return self.result(target, Status.UNSUPPORTED, detail="not_addressable")

            if request.light.present():
                await hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": target.entity_id, **request.light.as_turn_on_data()},
                    blocking=True,
                )

            on_time = round(request.duration_s, 1)
            await hass.services.async_call(
                "mqtt",
                "publish",
                {"topic": topic, "payload": json.dumps({"state": "ON", "on_time": on_time})},
                blocking=True,
            )
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)
