"""Live ZCL attribute reads through Zigbee2MQTT's generic `read` payload, one cluster at a time.

Z2M publishes a read's result only in the device's state, under the payload's state_property. Every state publish
carries Z2M's whole cached state, deep-merged, so a key it caches would ride in every later publish holding a past
read, and each read itself is preceded by one such publish. The key is therefore kept out of the cache with the
device's filtered_cache option, which `reader` adds first: then only a read's own reply carries it.

A read also updates the state Z2M keeps from the attributes it reads, as a report would: reading CurrentLevel sets
Z2M's brightness.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from homeassistant.components import mqtt
from homeassistant.components.light import ColorMode, brightness_supported
from homeassistant.core import HomeAssistant, callback

from .addressing import bridge_topic, state_topic, topic, z2m_address
from .bridge import ensure_options, wait
from ...core.models import Target

_LOGGER = logging.getLogger(__name__)

READ_KEY = "device_side_read"
_FILTERED_CACHE = "filtered_cache"
# Z2M publishes a reply within a quarter second when the bulb answers; the same wait as turn_on_for's state.
_REPLY_TIMEOUT_S = 5.0


def clusters(target: Target) -> dict[str, list[str]]:
    """The clusters and attributes to read for a light, by its supported color modes.

    One unsupported attribute fails a cluster's whole read, so only the color mode's own are asked for: a color
    temperature bulb has no hue or saturation, and some have no EnhancedColorMode.
    """
    modes = set((target.state and target.state.attributes.get("supported_color_modes")) or ())
    wanted = {"genOnOff": ["onOff", "onTime"]}
    if brightness_supported(modes):
        wanted["genLevelCtrl"] = ["currentLevel"]
    color = []
    if ColorMode.COLOR_TEMP in modes:
        color.append("colorTemperature")
    if ColorMode.XY in modes:
        color += ["currentX", "currentY"]
    if ColorMode.HS in modes:
        color += ["currentHue", "currentSaturation"]
    if color:
        wanted["lightingColorCtrl"] = ["colorMode", *color]
    return wanted


class Reader:
    """Reads devices one after another over one subscription to Z2M's log, which reports a failed read."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._reply: asyncio.Future[tuple[dict, dict]] | None = None
        self._expected: set[str] = set()
        self._failure: tuple[str, ...] = ()  # what Z2M's error line names for the read in flight

    @callback
    def _on_log(self, msg: mqtt.ReceiveMessage) -> None:
        # Z2M logs a failed read as: Publish 'set' 'read' to '<name>' failed: ... ZCL command <ieee>/<endpoint>
        # <cluster>.read([...]) failed (<status>).
        if self._reply is None or self._reply.done():
            return
        try:
            entry = json.loads(msg.payload)
            message = entry["message"]
        except ValueError, TypeError, KeyError:
            return
        if entry.get("level") == "error" and all(part in message for part in self._failure):
            self._reply.set_exception(RuntimeError(message))

    @callback
    def _on_state(self, msg: mqtt.ReceiveMessage) -> None:
        # A retained message is old state the broker resends on subscribe, not Z2M's answer.
        if msg.retain or self._reply is None or self._reply.done():
            return
        try:
            state = json.loads(msg.payload)
            value = state.get(READ_KEY)
        except ValueError, AttributeError:
            return
        if isinstance(value, dict) and set(value) == self._expected:
            self._reply.set_result((value, state))

    async def read(self, target: Target) -> dict:
        """The light's attributes from every cluster `clusters` names, merged, read one cluster after another.

        An off light's CurrentLevel is not read but taken from Z2M's brightness, which the OnOff reply carries: that
        is the level the light comes back at. The bulb's own isn't. After an off with a transition it holds the
        minimum, and Z2M restores the level it kept on the next on; just after a plain off, a Hue bulb's own fade
        still dims it. Reading it would also overwrite Z2M's brightness with it.

        Raises when a read fails: at once when Z2M logs the error, else after the timeout.
        """
        attributes: dict = {}
        state: dict = {}
        # HA's light entity already subscribes to the state topic, so this subscription is live at once.
        unsubscribe = await mqtt.async_subscribe(self.hass, state_topic(target), self._on_state)
        try:
            for cluster, names in clusters(target).items():
                if cluster == "genLevelCtrl" and not attributes["onOff"]:
                    if (brightness := state.get("brightness")) is not None:
                        attributes["currentLevel"] = brightness
                    continue
                self._reply, self._expected = self.hass.loop.create_future(), set(names)
                self._failure = (f"{z2m_address(target.device)}/", f"{cluster}.read(")
                payload = {"read": {"cluster": cluster, "attributes": names, "state_property": READ_KEY}}
                await self.hass.services.async_call(
                    "mqtt", "publish", {"topic": topic(target, "set"), "payload": json.dumps(payload)}, blocking=True
                )
                reply, state = await wait(self._reply, _REPLY_TIMEOUT_S, f"no {cluster} reply from Zigbee2MQTT")
                attributes |= reply
        finally:
            self._reply = None
            unsubscribe()
        return attributes


@asynccontextmanager
async def reader(hass: HomeAssistant, devices: list[Target]) -> AsyncIterator[Reader]:
    """A Reader for these devices, once each has the read key filtered from Z2M's cache; raises if one can't.

    The key goes into each device's filtered_cache, after the user's own entries.
    """
    reading = Reader(hass)
    # Subscribed before ensure_options subscribes to bridge/info, so both reach the broker in one batch: the retained
    # bridge/info arriving shows the log is subscribed too, before the first read.
    unsubscribe = await mqtt.async_subscribe(hass, bridge_topic("logging"), reading._on_log)
    try:
        by_address = {z2m_address(device.device): device for device in devices}

        def added(address: str) -> None:
            _LOGGER.info(
                "Added %s to Zigbee2MQTT's %s for %s, so get_attributes reads it live",
                READ_KEY,
                _FILTERED_CACHE,
                by_address[address].entity_id,
            )

        await ensure_options(hass, "device", list(by_address), _with_read_key, added)
        yield reading
    finally:
        unsubscribe()


def _with_read_key(options: dict) -> dict:
    cached_out = options.get(_FILTERED_CACHE) or []
    return {} if READ_KEY in cached_out else {_FILTERED_CACHE: [*cached_out, READ_KEY]}
