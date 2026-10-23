import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .capabilities import AdapterCapabilities
from .models import EntityResult, Request, Status, Target
from .runtime import get_runtime

_LOGGER = logging.getLogger(__name__)


class Adapter[RequestT: Request](ABC):
    """One feature on one platform. Instantiated once per registry."""

    feature: ClassVar[str]
    platform: ClassVar[str]
    capabilities: ClassVar[AdapterCapabilities]

    def supports(self, hass: HomeAssistant, request: RequestT, target: Target) -> str | None:
        """None if this adapter can serve the target, else a reason key. Sync and cheap: no I/O.

        The default checks the claimed domains, and on lights the claimed fields. Switches ignore light fields
        rather than refuse them; the dispatcher records that in the result's detail.
        """
        if target.domain not in self.capabilities.domains:
            return "domain_not_supported"
        if target.domain == "light" and request.fields_present() - self.capabilities.supports_fields:
            return "fields_not_supported"
        return None

    @abstractmethod
    async def execute(self, hass: HomeAssistant, request: RequestT, targets: list[Target]) -> list[EntityResult]:
        """Send the command to every target at once, so an adapter can batch or address a native group."""

    def result(self, target: Target, status: Status, **kwargs) -> EntityResult:
        return EntityResult(
            target.entity_id, status, platform=self.platform, mode=self.capabilities.mode, **kwargs
        )

    async def gather(
        self, hass: HomeAssistant, targets: list[Target], send: Callable[[Target], Awaitable[EntityResult]]
    ) -> list[EntityResult]:
        """Run send() per target under the platform's and this adapter's concurrency limits.

        An exception from one target becomes that target's REJECTED result and does not affect the others.
        """
        runtime = get_runtime(hass)
        platform_info = runtime.registry.platforms[self.platform]
        platform_limit = runtime.semaphore(f"platform:{self.platform}", platform_info.max_concurrency)
        adapter_limit = runtime.semaphore(f"adapter:{self.feature}:{self.platform}", self.capabilities.max_concurrency)

        async def _one(target: Target) -> EntityResult:
            async with platform_limit, adapter_limit:
                try:
                    return await send(target)
                except Exception as err:  # noqa: BLE001 - one device's failure must not abort the room
                    _LOGGER.warning("%s on %s failed for %s: %s", self.feature, self.platform, target.entity_id, err)
                    return self.result(target, Status.REJECTED, detail="error")

        return list(await asyncio.gather(*(_one(target) for target in targets)))
