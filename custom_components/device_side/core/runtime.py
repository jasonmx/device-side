import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from ..const import DOMAIN

if TYPE_CHECKING:
    from .dispatcher import Dispatcher
    from .registry import AdapterRegistry

DATA: HassKey[DeviceSideData] = HassKey(DOMAIN)


@dataclass(slots=True)
class DeviceSideData:
    registry: AdapterRegistry
    dispatcher: Dispatcher
    # Created lazily so each semaphore binds to the running loop, not the import executor's thread.
    semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    # Per-platform scratch state that outlives one call (the Hue transition cache).
    platform_state: dict[str, Any] = field(default_factory=dict)

    def semaphore(self, key: str, limit: int) -> asyncio.Semaphore:
        if (semaphore := self.semaphores.get(key)) is None:
            semaphore = self.semaphores[key] = asyncio.Semaphore(limit)
        return semaphore


def get_runtime(hass: HomeAssistant) -> DeviceSideData:
    return hass.data[DATA]
