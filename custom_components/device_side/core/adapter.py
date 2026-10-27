import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import ClassVar

from homeassistant.core import HomeAssistant

from .models import EntityResult, Request, Status, Target
from .runtime import get_runtime
from .scope import AdapterScope

_LOGGER = logging.getLogger(__name__)


class Adapter[RequestT: Request](ABC):
    """One action on one integration. Instantiated once per registry."""

    action: ClassVar[str]
    integration: ClassVar[str]
    scope: ClassVar[AdapterScope]

    def supports(self, hass: HomeAssistant, request: RequestT, target: Target) -> str | None:
        """None if this adapter can serve the target, else a reason key. Sync and cheap: no I/O.

        The default checks the domains in scope, and on lights the fields in scope. Switches ignore light fields
        rather than refuse them; the dispatcher records that in the result's detail.
        """
        if target.domain not in self.scope.domains:
            return "domain_not_tested"
        if target.domain == "light" and request.fields_present() - self.scope.fields:
            return "fields_not_tested"
        return None

    @abstractmethod
    async def execute(self, hass: HomeAssistant, request: RequestT, targets: list[Target]) -> list[EntityResult]:
        """Send the command to every target at once, so an adapter can batch or address a native group."""

    def result(self, target: Target, status: Status, **kwargs) -> EntityResult:
        """Build every result here: it keys on target.reported_id, which the dispatcher matches results by."""
        return EntityResult(target.reported_id, status, integration=self.integration, **kwargs)

    def limits(self, hass: HomeAssistant) -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
        """The integration's and this adapter's concurrency limits, which every command to a device runs under."""
        runtime = get_runtime(hass)
        integration_info = runtime.registry.integrations[self.integration]
        return (
            runtime.semaphore(f"integration:{self.integration}", integration_info.max_concurrency),
            runtime.semaphore(f"adapter:{self.action}:{self.integration}", self.scope.max_concurrency),
        )

    async def gather(
        self, hass: HomeAssistant, targets: list[Target], send: Callable[[Target], Awaitable[EntityResult]]
    ) -> list[EntityResult]:
        """Run send() per target under the integration's and this adapter's concurrency limits.

        An exception from one target becomes that target's REJECTED result and does not affect the others.
        """
        integration_limit, adapter_limit = self.limits(hass)

        async def _one(target: Target) -> EntityResult:
            async with integration_limit, adapter_limit:
                try:
                    return await send(target)
                except Exception as err:  # noqa: BLE001 - one device's failure must not abort the room
                    _LOGGER.warning("%s on %s failed for %s: %s", self.action, self.integration, target.entity_id, err)
                    return self.result(target, Status.REJECTED, detail="error")

        return list(await asyncio.gather(*(_one(target) for target in targets)))
