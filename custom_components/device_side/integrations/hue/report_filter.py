"""Tell the bridge's reports of our own fades from real changes, and forget a prediction a real change ends.

The bridge reports a fade's end value at its start, and the bulb reports points it has passed late (Tested behavior in
docs/integrations.md). Either is ours; anything else is a change made elsewhere, so the light's prediction is dropped
and the next move starts from what the bridge reports. A change made from Home Assistant drops it at once, whatever its
value, by watching light and scene service calls.
"""

import logging
from enum import Enum
from typing import TYPE_CHECKING

from aiohue.v2.controllers.events import EventType
from aiohue.v2.models.resource import ResourceTypes
from homeassistant.const import ATTR_DOMAIN, ATTR_ENTITY_ID, ATTR_SERVICE_DATA, ENTITY_MATCH_ALL, EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids

from .bridge import bridge_api
from .transition_cache import BRIGHTNESS, REPORT_TOLERANCE, TransitionCache, transition_cache
from ...core.models import Target
from ...core.runtime import get_runtime

if TYPE_CHECKING:
    from aiohue.v2 import HueBridgeV2

_LOGGER = logging.getLogger(__name__)

# The services whose calls can change a Hue light's brightness or on.
SERVICE_DOMAINS = frozenset({"light", "scene"})


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
    values = {}
    if (on := event.get("on")) is not None and "on" in on:
        values["on"] = on["on"]
    if (dimming := event.get("dimming")) is not None and "brightness" in dimming:
        values[BRIGHTNESS] = dimming["brightness"]
    if not values or not cache.follows(resource_id):
        return None
    reports = {_value(cache, resource_id, key, value) for key, value in values.items()}
    return next(report for report in (Report.REAL, Report.PATH, Report.ECHO) if report in reports)


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
    """One bridge's subscriber to its event stream and Home Assistant's listener for light and scene calls."""

    def __init__(self, hass: HomeAssistant, api: HueBridgeV2, entry_id: str) -> None:
        self.hass = hass
        self.api = api
        self.entry_id = entry_id
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

    def _on_event(self, event_type: EventType, data: dict | None) -> None:
        # Runs inside aiohue's event loop: an exception here would stop core hue's events too.
        try:
            if data is not None and classify(self.cache, self.api, data) is Report.REAL:
                self.cache.forget(data["id"])
        except Exception:
            _LOGGER.exception("Hue report filter failed on %s", data)

    @callback
    def _on_service_call(self, event: Event) -> None:
        service_data = event.data[ATTR_SERVICE_DATA] or {}
        if service_data.get(ATTR_ENTITY_ID) == ENTITY_MATCH_ALL:
            for light in self.api.lights:
                self.cache.forget(light.id)
            return
        selected = async_extract_referenced_entity_ids(self.hass, TargetSelection(service_data))
        for entity_id in selected.referenced | selected.indirectly_referenced:
            for light_id in self._lights(entity_id):
                self.cache.forget(light_id)

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


@callback
def _is_light_call(event_data) -> bool:
    return event_data[ATTR_DOMAIN] in SERVICE_DOMAINS


def attach_report_filter(hass: HomeAssistant, target: Target) -> None:
    """Attach the target's bridge's filter on first use, once per aiohue bridge: a reloaded hue entry gets a new one."""
    api = bridge_api(target)
    entry_id = target.config_entry.entry_id
    get_runtime(hass).listen(f"hue:{entry_id}", api, lambda: ReportFilter(hass, api, entry_id).attach())
