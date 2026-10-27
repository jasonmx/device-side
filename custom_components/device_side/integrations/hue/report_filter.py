"""Tell the bridge's reports of our own fades from real changes, and forget a prediction a real change ends.

The bridge reports a fade's end value at its start, and the bulb reports points it has passed late (Tested behavior in
docs/integrations.md). Either is ours; anything else is a change made elsewhere, so the light's prediction is dropped
and the next move starts from what the bridge reports. A change made from Home Assistant drops it at once, whatever its
value, by watching light and scene service calls.

With the predicted_state option on, the reports that are ours are hidden from aiohue, and so from HA, which instead
is sent what device_side predicts: the start value while a fade runs, the halt at a stop, the end once it has run.
Hiding works by editing the event's dict in a synchronous subscriber, which runs before aiohue's controllers apply it
in a task; what device_side sends goes through the same event stream in-process, never to the bridge.
"""

import logging
from collections.abc import Awaitable
from enum import Enum
from inspect import iscoroutinefunction
from statistics import mean
from typing import TYPE_CHECKING

from aiohue.v2.controllers.events import EventType
from aiohue.v2.models.resource import ResourceTypes
from homeassistant.const import ATTR_DOMAIN, ATTR_ENTITY_ID, ATTR_SERVICE_DATA, ENTITY_MATCH_ALL, EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids

from .bridge import bridge_api
from .transition_cache import BRIGHTNESS, MIN_BRIGHTNESS_STEP, REPORT_TOLERANCE, TransitionCache, transition_cache
from ...core.models import Target
from ...core.runtime import get_runtime

if TYPE_CHECKING:
    from aiohue.v2 import HueBridgeV2

_LOGGER = logging.getLogger(__name__)

# The services whose calls can change a Hue light's brightness or on.
SERVICE_DOMAINS = frozenset({"light", "scene"})
# Marks an event device_side sends in the bridge's place. aiohue reads only its models' fields, so ignores it.
MARKER = "device_side"


class Report(Enum):
    ECHO = "echo"  # an end value a write of ours made the bridge report
    PATH = "path"  # the bulb reporting a point it has passed, late; or a room, whose lights decide
    REAL = "real"  # a change made elsewhere


def classify(cache: TransitionCache, api: HueBridgeV2, event: dict) -> Report | None:
    """What a light's or grouped_light's update is, or None when it holds no brightness or on Device Side follows.

    A light's event is real if any of its values is neither an armed end value nor on the path travelled. A
    grouped_light's is never real on its own while one of its lights is followed: a real change to the room changes
    its lights too, and their events decide.
    """
    resource_id = event["id"]
    if event.get("type") == ResourceTypes.GROUPED_LIGHT.value:
        lights = api.groups.grouped_light.get_lights(resource_id)
        return Report.PATH if any(cache.follows(light.id) for light in lights) else None
    values = reported_values(event)
    if not values or not cache.follows(resource_id):
        return None
    reports = {_value(cache, resource_id, key, value) for key, value in values.items()}
    return next(report for report in (Report.REAL, Report.PATH, Report.ECHO) if report in reports)


def reported_values(event: dict) -> dict[str, float | bool]:
    """The event's on and brightness, keyed "on" and "brightness"; only what changed is in an event."""
    values: dict[str, float | bool] = {}
    if (on := event.get("on")) is not None and "on" in on:
        values["on"] = on["on"]
    if (dimming := event.get("dimming")) is not None and "brightness" in dimming:
        values[BRIGHTNESS] = dimming["brightness"]
    return values


def _value(cache: TransitionCache, light_id: str, key: str, value: float | bool) -> Report:
    if cache.echoed(light_id, key, value):
        return Report.ECHO
    if key == BRIGHTNESS:
        return Report.PATH if cache.on_path(light_id, BRIGHTNESS, value) else Report.REAL
    # on: true while the path is lit (the 17 % report mid soft off), on: false once it has reached 0.
    if (path := cache.path(light_id, BRIGHTNESS)) is None:
        return Report.REAL
    lit = path[1] > REPORT_TOLERANCE if value else path[0] <= REPORT_TOLERANCE
    return Report.PATH if lit else Report.REAL


class ReportFilter:
    """One bridge's subscriber to its event stream and Home Assistant's listener for light and scene calls.

    hiding is the predicted_state option, as attached: off, the filter only observes.
    """

    def __init__(self, hass: HomeAssistant, api: HueBridgeV2, entry_id: str, hiding: bool) -> None:
        self.hass = hass
        self.api = api
        self.entry_id = entry_id
        self.hiding = hiding
        self.cache = transition_cache(hass)

    def attach(self) -> CALLBACK_TYPE:
        # Synchronous, so it runs before aiohue's controllers apply the event: they handle it in a task.
        unsubscribe = self.api.events.subscribe(
            self._on_event,
            event_filter=EventType.RESOURCE_UPDATED,
            resource_filter=(ResourceTypes.LIGHT, ResourceTypes.GROUPED_LIGHT),
        )
        unlisten = self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._on_service_call, event_filter=_is_light_call)

        def detach() -> None:
            unsubscribe()
            unlisten()

        return detach

    def fading(self, ends: dict[str, float], duration: float) -> None:
        """Show each light's end value once its fade has run, in place of any end still to show."""
        if not self.hiding:
            return
        for light_id, target in ends.items():

            async def show_end(light_id: str = light_id, target: float = target) -> None:
                self.show({light_id: target})

            get_runtime(self.hass).schedule(self.hass, _end_key(light_id), [(duration, show_end)])

    def halted(self, halts: dict[str, float]) -> None:
        """Show each light where a stop halted it, and drop the end its fade would have shown."""
        if not self.hiding:
            return
        for light_id in halts:
            get_runtime(self.hass).schedule(self.hass, _end_key(light_id), [])
        self.show(halts)

    def show(self, brightness: dict[str, float]) -> None:
        """Send aiohue, and so HA, each light's brightness and its rooms'. 0 is off, leaving the stored brightness
        alone, as a soft off does on the bridge."""
        for light_id, value in brightness.items():
            event: dict = {"id": light_id, "type": ResourceTypes.LIGHT.value, MARKER: True}
            if value > 0:
                event |= {"on": {"on": True}, "dimming": {"brightness": value}}
            else:
                event["on"] = {"on": False}
            self.api.events.emit(EventType.RESOURCE_UPDATED, event)
        self._show_rooms_soon(self._rooms(brightness))

    def _on_event(self, event_type: EventType, data: dict | None) -> None:
        # Runs inside aiohue's event loop: an exception here would stop core hue's events too.
        try:
            if data is None or data.get(MARKER):
                return
            report = classify(self.cache, self.api, data)
            if self.hiding and report in (Report.ECHO, Report.PATH):
                self._hide(data, report)
                return
            if data.get("type") == ResourceTypes.LIGHT.value:
                self.cache.shown(data["id"], reported_values(data))
            if report is Report.REAL:
                forget(self.hass, data["id"])
                if self.hiding:
                    self._show_rooms_soon(self._rooms([data["id"]]))
        except Exception:
            _LOGGER.exception("Hue report filter failed on %s", data)

    def _hide(self, data: dict, report: Report) -> None:
        """Take our own report's on and brightness out of the event before aiohue applies it.

        A move up from off still shows on, at the light's dimmest, so HA doesn't hold it off for the whole fade.
        A room shows what its lights are shown, once aiohue has applied them.
        """
        resource_id = data["id"]
        if data.get("type") == ResourceTypes.GROUPED_LIGHT.value:
            _strip(data)
            self._show_rooms_soon({resource_id})
            return
        values = reported_values(data)
        self.cache.hidden(resource_id, values)
        light = self.api.lights.get(resource_id)
        if report is Report.ECHO and values.get("on") is True and light is not None and not light.on.on:
            dimmest = (light.dimming.min_dim_level if light.dimming else None) or MIN_BRIGHTNESS_STEP
            data["on"] = {"on": True}
            data["dimming"] = {**data.get("dimming", {}), "brightness": dimmest}
            self._show_rooms_soon(self._rooms([resource_id]))
            return
        _strip(data)

    def _rooms(self, light_ids) -> set[str]:
        """The grouped_lights of the rooms and zones holding any of the lights."""
        return {
            group.id
            for group in self.api.groups.grouped_light
            if any(light.id in light_ids for light in self.api.groups.grouped_light.get_lights(group.id))
        }

    def _show_rooms_soon(self, grouped_light_ids: set[str]) -> None:
        # After aiohue's controllers have applied what is pending: their tasks were queued before this.
        if grouped_light_ids:
            self.hass.loop.call_soon(self._show_rooms, grouped_light_ids)

    def _show_rooms(self, grouped_light_ids: set[str]) -> None:
        """Send each room on while any of its lights is, at the mean of its lit lights, as HA averages them."""
        try:
            for grouped_light_id in grouped_light_ids:
                if (group := self.api.groups.grouped_light.get(grouped_light_id)) is None:
                    continue
                lights = self.api.groups.grouped_light.get_lights(grouped_light_id)
                lit = [light for light in lights if light.on.on]
                event: dict = {"id": grouped_light_id, "type": ResourceTypes.GROUPED_LIGHT.value, MARKER: True}
                event["on"] = {"on": bool(lit)}
                if group.dimming is not None and (
                    dimmed := [light.dimming.brightness for light in lit if light.dimming]
                ):
                    event["dimming"] = {"brightness": mean(dimmed)}
                self.api.events.emit(EventType.RESOURCE_UPDATED, event)
        except Exception:
            _LOGGER.exception("Hue report filter failed showing rooms %s", grouped_light_ids)

    @callback
    def _on_service_call(self, event: Event) -> None:
        service_data = event.data[ATTR_SERVICE_DATA] or {}
        if service_data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL:
            for light in self.api.lights:
                forget(self.hass, light.id)
            return
        selected = async_extract_referenced_entity_ids(self.hass, TargetSelection(service_data))
        for entity_id in selected.referenced | selected.indirectly_referenced:
            for light_id in self._lights(entity_id):
                forget(self.hass, light_id)

    def _lights(self, entity_id: str) -> list[str]:
        """The bridge's lights behind a Hue light, room, zone or scene entity of this bridge."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None or entry.platform != "hue" or entry.config_entry_id != self.entry_id:
            return []
        resource_id = entry.unique_id
        if entry.domain == "scene":
            if (scene := self.api.scenes.scene.get(resource_id)) is None:
                return []
            group = scene.group.rid
            lights = self.api.groups.room.get_lights(group) or self.api.groups.zone.get_lights(group)
        elif self.api.lights.get(resource_id) is not None:
            return [resource_id]
        else:
            lights = self.api.groups.grouped_light.get_lights(resource_id)
        return [light.id for light in lights]


def _strip(data: dict) -> None:
    data.pop("on", None)
    if (dimming := data.get("dimming")) is not None:
        dimming.pop("brightness", None)


def _end_key(light_id: str) -> str:
    return f"hue-end:{light_id}"


def forget(hass: HomeAssistant, light_id: str) -> None:
    """A change made other than by a move or stop: drop the light's prediction and the fade end still to show."""
    transition_cache(hass).forget(light_id)
    get_runtime(hass).schedule(hass, _end_key(light_id), [])


async def write_forgetting(hass: HomeAssistant, light_id: str, write: Awaitable) -> None:
    """Forget the light before the write, so its report reaches HA rather than being taken for the bulb's own. A
    refused write left the light where its move had it, so the prediction comes back."""
    cache = transition_cache(hass)
    forgotten = cache.forget(light_id)
    try:
        await write
    except Exception:
        cache.restore(light_id, forgotten)
        raise
    get_runtime(hass).schedule(hass, _end_key(light_id), [])


def applies_later(api: HueBridgeV2) -> bool:
    """Whether aiohue's light and grouped_light controllers apply an event in a task, after our subscriber has run:
    hiding a report depends on it."""
    return all(iscoroutinefunction(c._handle_event) for c in (api.lights, api.groups.grouped_light))


@callback
def _is_light_call(event_data) -> bool:
    return event_data[ATTR_DOMAIN] in SERVICE_DOMAINS


def report_filter(hass: HomeAssistant, target: Target) -> ReportFilter:
    """The target's bridge's filter, attached on first use once per aiohue bridge: a reloaded hue entry gets a new one,
    and a reloaded device_side entry (an option saved) a new one on the next move or stop."""
    api = bridge_api(target)
    entry_id = target.config_entry.entry_id
    runtime = get_runtime(hass)
    filters = runtime.integration_state.setdefault("hue_filters", {})

    def attach() -> CALLBACK_TYPE:
        hiding = runtime.predicted_state
        if hiding and not applies_later(api):
            _LOGGER.warning("This aiohue applies bridge events at once, so Hue fades show what the bridge reports")
            hiding = False
        filters[entry_id] = ReportFilter(hass, api, entry_id, hiding)
        return filters[entry_id].attach()

    runtime.listen(f"hue:{entry_id}", api, attach)
    return filters[entry_id]
