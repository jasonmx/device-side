"""Tell the bridge's reports of our own fades from real changes, and forget a prediction a real change ends.

The bridge reports a fade's end value at its start, and the bulb reports late, stale values, and off any straight line
(Tested behavior in docs/integrations.md), so no value tells ours apart. Instead, while a move or stop on a light is
inside its guard window, every report of the keys its attribute owns (attributes.ATTRIBUTES) is ours, except a switch
to off while the light's brightness heads somewhere lit: that is the Hue app, a dimmer or a Hue automation, so the
light's prediction is dropped and the next move starts from what the bridge reports. A change made from Home Assistant
drops it at once, whatever its value, by watching light and scene service calls.

With the predicted_state option on, the reports that are ours are hidden from aiohue, and so from HA, which instead
is sent what device_side predicts: the start value while a fade runs, the halt at a stop, the end once it has run.
Hiding works by editing the event's dict in a synchronous subscriber, which runs before aiohue's controllers apply it
in a task; what device_side sends goes through the same event stream in-process, never to the bridge.
"""

import logging
from collections.abc import Awaitable, Iterable
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

from .attributes import ATTRIBUTES, event_fields, reported_values, strip
from .bridge import bridge_api
from .transition_cache import BRIGHTNESS, MIN_BRIGHTNESS_STEP, TransitionCache, transition_cache
from ...core.models import Target
from ...core.runtime import get_runtime

if TYPE_CHECKING:
    from aiohue.v2 import HueBridgeV2
    from aiohue.v2.models.light import Light

_LOGGER = logging.getLogger(__name__)

# The services whose calls can change a Hue light's brightness or on.
SERVICE_DOMAINS = frozenset({"light", "scene"})
# Marks an event device_side sends in the bridge's place. aiohue reads only its models' fields, so ignores it.
MARKER = "device_side"
# Where each bridge's ReportFilter lives in integration_state, by hue config entry.
FILTERS = "hue_filters"


class Report(Enum):
    OURS = "ours"  # a report of a key a live transition owns: the bridge's or the bulb's report of our fade or stop
    REAL = "real"  # a change made elsewhere


def owned(cache: TransitionCache, api: HueBridgeV2, event: dict) -> frozenset[str]:
    """The report keys a live transition owns: on a light, its own; on a grouped_light, any of its lights'."""
    if event.get("type") == ResourceTypes.GROUPED_LIGHT.value:
        resource_ids = [light.id for light in api.groups.grouped_light.get_lights(event["id"])]
    else:
        resource_ids = [event["id"]]
    return frozenset(
        key for rid in resource_ids for attribute in cache.attributes(rid) for key in ATTRIBUTES[attribute].keys
    )


def classify(cache: TransitionCache, api: HueBridgeV2, event: dict) -> Report | None:
    """What a light's or grouped_light's update is, or None when it reports no key a live transition owns.

    A grouped_light's is never real on its own: a real change to the room changes its lights too, and their events
    decide.
    """
    values = reported_values(event)
    if not owned(cache, api, event) & values.keys():
        return None
    if values.get("on") is False and event.get("type") == ResourceTypes.LIGHT.value:
        # Our soft off reports off; off while the light heads somewhere lit, or holds a halt, is a switch elsewhere.
        if (transition := cache.live(event["id"], BRIGHTNESS)) is not None and transition.target > 0:
            return Report.REAL
    return Report.OURS


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
            # Nothing will show a running fade's end now: hand HA back to the bridge.
            for light in self.api.lights:
                if _running(self.cache, light.id):
                    self.hand_back(light.id)

        return detach

    def fading(self, attribute: str, ends: dict[str, float], duration: float) -> None:
        """Show each light's end value once its fade has run, in place of any end of the attribute still to show.

        A light HA shows off, faded up from off, is shown on at its dimmest at once, so HA doesn't hold it off for the
        whole fade.
        """
        if not self.hiding:
            return
        for light_id, target in ends.items():

            async def show_end(light_id: str = light_id, target: float = target) -> None:
                self.show(attribute, {light_id: target})

            get_runtime(self.hass).schedule(self.hass, _end_key(light_id, attribute), [(duration, show_end)])
        if attribute == BRIGHTNESS:
            lights = [self.api.lights.get(light_id) for light_id, target in ends.items() if target > 0]
            self.show(BRIGHTNESS, {light.id: _dimmest(light) for light in lights if light and not light.on.on})

    def halted(self, attribute: str, halts: dict[str, float]) -> None:
        """Show each light where a stop halted it, and drop the end its fade would have shown."""
        if not self.hiding:
            return
        for light_id in halts:
            get_runtime(self.hass).schedule(self.hass, _end_key(light_id, attribute), [])
        self.show(attribute, halts)

    def show(self, attribute: str, values: dict[str, float]) -> None:
        """Send aiohue, and so HA, each light's value of the attribute, and its rooms'."""
        for light_id, value in values.items():
            event: dict = {"id": light_id, "type": ResourceTypes.LIGHT.value, MARKER: True}
            self.api.events.emit(EventType.RESOURCE_UPDATED, event | event_fields(ATTRIBUTES[attribute].shows(value)))
        self._show_rooms_soon(self._rooms(values))

    def hand_back(self, light_id: str) -> None:
        """Send aiohue what the bridge last reported for the light and HA was not shown: nothing predicts it now."""
        if not self.hiding or not (held := self.cache.release(light_id)):
            return
        event: dict = {"id": light_id, "type": ResourceTypes.LIGHT.value, MARKER: True}
        self.api.events.emit(EventType.RESOURCE_UPDATED, event | event_fields(held))
        self._show_rooms_soon(self._rooms([light_id]))

    def _on_event(self, event_type: EventType, data: dict | None) -> None:
        # Runs inside aiohue's event loop: an exception here would stop core hue's events too.
        try:
            if data is None or data.get(MARKER):
                return
            report = classify(self.cache, self.api, data)
            if self.hiding and report is Report.OURS:
                self._hide(data)
            if data.get("type") == ResourceTypes.LIGHT.value:
                self.cache.shown(data["id"], reported_values(data))
            if report is Report.REAL:
                forget(self.hass, data["id"])
                if self.hiding:
                    self._show_rooms_soon(self._rooms([data["id"]]))
        except Exception:
            _LOGGER.exception("Hue report filter failed on %s", data)

    def _hide(self, data: dict) -> None:
        """Take the report keys a live transition owns out of the event before aiohue applies it; the rest pass.

        A room shows what its lights are shown, once aiohue has applied them.
        """
        keys = owned(self.cache, self.api, data)
        if data.get("type") == ResourceTypes.GROUPED_LIGHT.value:
            self._show_rooms_soon({data["id"]})
        else:
            self.cache.hidden(data["id"], {key: value for key, value in reported_values(data).items() if key in keys})
        strip(data, keys)

    def _rooms(self, light_ids: Iterable[str]) -> set[str]:
        """The grouped_lights of the rooms and zones holding any of the lights."""
        light_ids = set(light_ids)
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


def _dimmest(light: Light) -> float:
    return (light.dimming.min_dim_level if light.dimming else None) or MIN_BRIGHTNESS_STEP


def _running(cache: TransitionCache, light_id: str) -> bool:
    """Whether a move of any attribute is still under way on the light."""
    return any(cache.running(light_id, attribute) is not None for attribute in ATTRIBUTES)


def _end_key(light_id: str, attribute: str) -> str:
    return f"hue-end:{light_id}:{attribute}"


def forget(hass: HomeAssistant, light_id: str) -> None:
    """A change made other than by a move or stop: drop the light's prediction and the fade end still to show."""
    cache = transition_cache(hass)
    running = _running(cache, light_id)
    cache.forget(light_id)
    _forgotten(hass, light_id, running)


async def write_forgetting(hass: HomeAssistant, light_id: str, write: Awaitable) -> None:
    """Forget the light before the write, so its report reaches HA rather than being taken for the bulb's own. A
    refused write left the light where its move had it, so the prediction comes back."""
    cache = transition_cache(hass)
    running = _running(cache, light_id)
    forgotten = cache.forget(light_id)
    try:
        await write
    except Exception:
        cache.restore(forgotten)
        raise
    _forgotten(hass, light_id, running)


def _forgotten(hass: HomeAssistant, light_id: str, running: bool) -> None:
    """Drop the end still to show. A fade still running goes on to the end the bridge reported at its start, so HA
    is shown that, as it would be with predicted_state off; a write's own report, before or after, wins. A halt
    stays shown: the bridge's late report of it may never come."""
    for attribute in ATTRIBUTES:
        get_runtime(hass).schedule(hass, _end_key(light_id, attribute), [])
    if running:
        for reports in get_runtime(hass).integration_state.get(FILTERS, {}).values():
            if reports.api.lights.get(light_id) is not None:
                reports.hand_back(light_id)


def applies_later(api: HueBridgeV2) -> bool:
    """Whether aiohue's light and grouped_light controllers apply an event in a task, after our subscriber has run:
    hiding a report depends on it. _handle_event is private to aiohue: one without it is taken to apply at once."""
    return all(
        iscoroutinefunction(getattr(c, "_handle_event", None)) for c in (api.lights, api.groups.grouped_light)
    )


@callback
def _is_light_call(event_data) -> bool:
    return event_data[ATTR_DOMAIN] in SERVICE_DOMAINS


def report_filter(hass: HomeAssistant, target: Target) -> ReportFilter:
    """The target's bridge's filter, attached on first use once per aiohue bridge: a reloaded hue entry gets a new one,
    and a reloaded device_side entry (an option saved) a new one on the next move or stop."""
    api = bridge_api(target)
    entry_id = target.config_entry.entry_id
    runtime = get_runtime(hass)
    filters = runtime.integration_state.setdefault(FILTERS, {})

    def attach() -> CALLBACK_TYPE:
        hiding = runtime.predicted_state
        if hiding and not applies_later(api):
            _LOGGER.warning("This aiohue applies bridge events at once, so Hue fades show what the bridge reports")
            hiding = False
        filters[entry_id] = ReportFilter(hass, api, entry_id, hiding)
        return filters[entry_id].attach()

    runtime.listen(f"hue:{entry_id}", api, attach)
    return filters[entry_id]
