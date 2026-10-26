"""Zigbee2MQTT turn_on_for: optional light.turn_on, mqtt.publish with on_time, then state read-backs."""

import json
import logging
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import topic
from ...actions.turn_on_for import TurnOnForRequest
from ...core.adapter import Adapter
from ...core.models import EntityResult, Status, Target
from ...core.runtime import get_runtime
from ...core.scope import AdapterScope, DurationLimits

_LOGGER = logging.getLogger(__name__)

# Zigbee OnWithTimedOff: on_time in tenths of a second (uint16), range 1-65534 tenths.
# 65534 tenths = 6553.4 s. The 50 ms floor from core/duration.py handles the effective minimum.
_TIMER_LIMITS = DurationLimits(min_s=0, max_s=6553.4)

# Read-back delays in seconds. The second end read allows for a bulb clock that runs slow on a long timer.
_ON_READ_S = 1.0
_END_READ_S = 1.0
_LATE_END_READ_MIN_S = 5.0
_LATE_END_READ_FRACTION = 0.02


class Z2MTurnOnFor(Adapter[TurnOnForRequest]):
    """Turn a Z2M light on for a duration using Zigbee2MQTT's on_time attribute.

    With fields: calls light.turn_on first (blocking) so HA's MQTT light entity applies brightness,
    color and transition through its own protocol, then publishes {"state":"ON","on_time":<seconds, 1dp>}
    to the device's command topic. Without fields: publishes only.

    Z2M publishes no state for a timed command, and Hue bulbs on Z2M don't report, so HA's state would go
    stale. The adapter then asks Z2M to read the state back ({"state":""} on the get topic): 1 s after the
    publish when no fields ran light.turn_on, and twice after the timer should end. A new call on the same
    target replaces its pending reads.

    Returns SENT (fire-and-forget via MQTT); the bridge forwards the command to the device. The reads never
    change the result.
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
        if topic(target, "set") is None:
            return "not_addressable"
        return None

    async def execute(
        self, hass: HomeAssistant, request: TurnOnForRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def send(target: Target) -> EntityResult:
            set_topic = topic(target, "set")
            if set_topic is None:  # defense in depth; supports() already refused this target
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
                {"topic": set_topic, "payload": json.dumps({"state": "ON", "on_time": on_time})},
                blocking=True,
            )
            self._schedule_reads(hass, target, on_time, read_on=not request.light.present())
            return self.result(target, Status.SENT)

        return await self.gather(hass, targets, send)

    def _schedule_reads(self, hass: HomeAssistant, target: Target, on_time: float, read_on: bool) -> None:
        get_topic = topic(target, "get")

        async def read() -> None:
            try:
                # Blocking, so a failure lands here rather than in HA's error log; the read runs in its own task.
                await hass.services.async_call(
                    "mqtt", "publish", {"topic": get_topic, "payload": json.dumps({"state": ""})}, blocking=True
                )
            except Exception as err:  # noqa: BLE001 - a failed read leaves HA's state stale, nothing more
                _LOGGER.debug("State read for %s failed: %s", target.entity_id, err)

        delays = [on_time + _END_READ_S, on_time + max(_LATE_END_READ_MIN_S, _LATE_END_READ_FRACTION * on_time)]
        if read_on:
            delays.insert(0, _ON_READ_S)
        get_runtime(hass).schedule(
            hass, f"{self.integration}:{self.action}:{target.entity_id}", ((delay, read) for delay in delays)
        )
