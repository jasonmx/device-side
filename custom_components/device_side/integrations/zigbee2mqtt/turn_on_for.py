"""Zigbee2MQTT turn_on_for: optional light.turn_on, mqtt.publish with on_time, then state read-backs."""

import asyncio
import json
import logging
from typing import ClassVar

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .addressing import state_topic, topic
from .native_control import COLOR_FIELDS, ensure_native_control
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
# Z2M publishes a light's state once the command has reached it: under a second, or seconds on a busy mesh.
_STATE_TIMEOUT_S = 5.0


class Z2MTurnOnFor(Adapter[TurnOnForRequest]):
    """Turn a Z2M light on for a duration using Zigbee2MQTT's on_time attribute.

    With fields: calls light.turn_on first so HA's MQTT light entity applies brightness, color and
    transition through its own protocol, waits for Z2M to publish the light's state, then publishes
    {"state":"ON","on_time":<seconds, 1dp>} to the device's command topic. Without fields: publishes only.
    With a color or color temperature, a Hue light (or a group with a Hue member) first gets Z2M's
    hue_native_control turned on (native_control.py), so it lights in that color rather than its last one.

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
            set_topic = topic(target, "set")  # supports() refused the targets it can't address

            if request.light.present() & COLOR_FIELDS:
                await ensure_native_control(hass, target)
            if request.light.present():
                await self._turn_on(hass, target, request.light.as_turn_on_data())

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

    async def _turn_on(self, hass: HomeAssistant, target: Target, data: dict) -> None:
        """light.turn_on, returning once Z2M publishes the light's state, so the timer follows the fields.

        HA returns once it has published the command, and Z2M handles two messages for one light at once. The
        timer's message would then publish the state from before the fields landed, which HA keeps, and contend
        with them on the mesh, starting the timer late. With no state by the timeout, the timer goes anyway.
        """
        service_data = {"entity_id": target.entity_id, **data}
        if (light_topic := state_topic(target)) is None:
            await hass.services.async_call("light", "turn_on", service_data, blocking=True)
            return

        published: asyncio.Future[None] = hass.loop.create_future()

        @callback
        def received(msg: mqtt.ReceiveMessage) -> None:
            # A retained message is old state the broker resends on subscribe, not Z2M's answer.
            if not msg.retain and not published.done():
                published.set_result(None)

        # HA's own light entity subscribes to this topic, so the subscription is live at once.
        unsubscribe = await mqtt.async_subscribe(hass, light_topic, received)
        try:
            await hass.services.async_call("light", "turn_on", service_data, blocking=True)
            try:
                async with asyncio.timeout(_STATE_TIMEOUT_S):
                    await published
            except TimeoutError:
                _LOGGER.warning(
                    "No state from Zigbee2MQTT for %s in %s s, "
                    "so its timer starts late and it stays on that much longer",
                    target.entity_id,
                    _STATE_TIMEOUT_S,
                )
        finally:
            unsubscribe()

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
