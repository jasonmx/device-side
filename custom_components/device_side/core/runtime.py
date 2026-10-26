import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.util.hass_dict import HassKey

from ..const import DOMAIN

if TYPE_CHECKING:
    from .dispatcher import Dispatcher
    from .registry import AdapterRegistry

DATA: HassKey[DeviceSideData] = HassKey(DOMAIN)

type Job = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class DeviceSideData:
    registry: AdapterRegistry
    dispatcher: Dispatcher
    # Created lazily so each semaphore binds to the running loop, not the import executor's thread.
    semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    # Per-integration scratch state that outlives one call (the Hue transition cache).
    integration_state: dict[str, Any] = field(default_factory=dict)
    # Delayed jobs not yet run, by the caller's key (the Z2M read-backs after a timer).
    pending: dict[str, list[CALLBACK_TYPE]] = field(default_factory=dict)

    def semaphore(self, key: str, limit: int) -> asyncio.Semaphore:
        if (semaphore := self.semaphores.get(key)) is None:
            semaphore = self.semaphores[key] = asyncio.Semaphore(limit)
        return semaphore

    def schedule(self, hass: HomeAssistant, key: str, jobs: Iterable[tuple[float, Job]]) -> None:
        """Run each job after its delay in seconds, cancelling whatever was still pending under key."""
        for unsub in self.pending.pop(key, []):
            unsub()
        handles: list[CALLBACK_TYPE] = []
        for delay, job in jobs:
            handles.append(self._call_later(hass, key, handles, delay, job))
        if handles:
            self.pending[key] = handles

    def cancel_pending(self) -> None:
        for handles in self.pending.values():
            for unsub in handles:
                unsub()
        self.pending.clear()

    def _call_later(
        self, hass: HomeAssistant, key: str, handles: list[CALLBACK_TYPE], delay: float, job: Job
    ) -> CALLBACK_TYPE:
        async def fire(_now) -> None:
            handles.remove(unsub)
            # A reschedule may have replaced this list since the timer fired; leave the new one alone.
            if not handles and self.pending.get(key) is handles:
                del self.pending[key]
            await job()

        unsub = async_call_later(hass, delay, fire)
        return unsub


def get_runtime(hass: HomeAssistant) -> DeviceSideData:
    return hass.data[DATA]
