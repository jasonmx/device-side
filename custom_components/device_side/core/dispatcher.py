import asyncio
import logging
from dataclasses import replace

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service import async_extract_entity_ids

from . import duration
from .cell import Cell
from .feature import Feature
from .groups import expand_ha_groups
from .models import FAILED, EntityResult, Request, Status, Target, TimedRequest
from .registry import CellRegistry
from .resolver import resolve
from ..const import CELL_TIMEOUT_S, DOMAIN

_LOGGER = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, hass: HomeAssistant, registry: CellRegistry):
        self.hass = hass
        self.registry = registry

    async def handle(self, feature: type[Feature], call: ServiceCall) -> ServiceResponse:
        request = feature.parse(self.hass, call)
        # expand_group=False: we expand group.* ourselves so members remember which group they came from.
        entity_ids = sorted(await async_extract_entity_ids(call, expand_group=False))
        if not entity_ids:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_targets")

        members, empty_groups = expand_ha_groups(self.hass, entity_ids)
        early = [EntityResult(group, Status.UNSUPPORTED, detail="empty_group") for group in empty_groups]
        targets: list[Target] = []
        for entity_id, via_group in members.items():
            target = resolve(self.hass, self.registry, entity_id, via_group)
            if isinstance(target, str):
                early.append(EntityResult(entity_id, Status.UNSUPPORTED, detail=target))
            elif target.domain not in feature.domains:
                early.append(
                    EntityResult(entity_id, Status.UNSUPPORTED, platform=target.platform, detail="domain_not_supported")
                )
            else:
                targets.append(target)

        results = (await feature.run(self.hass, request, targets, self) if targets else []) + early
        order = {entity_id: index for index, entity_id in enumerate([*members, *empty_groups])}
        results.sort(key=lambda result: order.get(result.entity_id, len(order)))

        if all(result.status in FAILED for result in results):
            summary = ", ".join(f"{result.entity_id}: {result.detail or result.status}" for result in results)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="all_targets_failed",
                translation_placeholders={"summary": summary},
            )
        if not call.return_response:
            return None
        return {result.entity_id: result.as_response() for result in results}

    async def run_cells(self, feature_key: str, request: Request, targets: list[Target]) -> list[EntityResult]:
        """Bucket targets by cell, expand native groups a cell can't address, run every cell concurrently.

        Returns exactly one result per (expanded) target.
        """
        results: list[EntityResult] = []
        buckets: dict[str, tuple[Cell, list[Target]]] = {}
        for target in targets:
            if (cell := self.registry.cell(feature_key, target.platform)) is None:
                results.append(EntityResult(target.entity_id, Status.UNSUPPORTED, target.platform, detail="no_cell"))
                continue
            buckets.setdefault(target.platform, (cell, []))[1].append(target)

        runs = []
        for cell, bucket in buckets.values():
            bucket = self._expand_native_groups(cell, bucket, results)
            ready = []
            for target in bucket:
                if reason := cell.supports(self.hass, request, target):
                    results.append(cell.result(target, Status.UNSUPPORTED, detail=reason))
                else:
                    ready.append(target)
            if ready:
                runs.append(self._run_cell(cell, request, ready))

        for cell_results in await asyncio.gather(*runs):
            results.extend(cell_results)
        return results

    def _expand_native_groups(self, cell: Cell, bucket: list[Target], results: list[EntityResult]) -> list[Target]:
        if cell.capabilities.native_groups or not any(target.is_group for target in bucket):
            return bucket
        expand = self.registry.platforms[cell.platform].expand_group
        expanded: list[Target] = []
        for target in bucket:
            if not target.is_group:
                expanded.append(target)
            elif expand is None:
                results.append(cell.result(target, Status.UNSUPPORTED, detail="group_not_supported"))
            else:
                expanded.extend(expand(self.hass, target))
        seen: set[str] = set()
        return [target for target in expanded if not (target.entity_id in seen or seen.add(target.entity_id))]

    async def _run_cell(self, cell: Cell, request: Request, targets: list[Target]) -> list[EntityResult]:
        clamped_to = None
        if isinstance(request, TimedRequest) and cell.capabilities.duration is not None:
            request, clamped_to = duration.clamp(request, cell.capabilities.duration)
        try:
            async with asyncio.timeout(CELL_TIMEOUT_S):
                raw = await cell.execute(self.hass, request, targets)
        except TimeoutError:
            _LOGGER.warning("%s on %s timed out after %ss", cell.feature, cell.platform, CELL_TIMEOUT_S)
            return [cell.result(target, Status.REJECTED, detail="timeout") for target in targets]
        except Exception:
            _LOGGER.exception("%s on %s failed", cell.feature, cell.platform)
            return [cell.result(target, Status.REJECTED, detail="error") for target in targets]
        return self._reconcile(cell, request, targets, raw, clamped_to)

    def _reconcile(
        self,
        cell: Cell,
        request: Request,
        targets: list[Target],
        raw: list[EntityResult],
        clamped_to: float | None,
    ) -> list[EntityResult]:
        by_id: dict[str, EntityResult] = {}
        for result in raw:
            if result.entity_id in by_id or result.entity_id not in {target.entity_id for target in targets}:
                _LOGGER.debug("%s on %s: dropping stray result for %s", cell.feature, cell.platform, result.entity_id)
                continue
            by_id[result.entity_id] = result
        ignored = bool(request.fields_present())
        out = []
        for target in targets:
            result = by_id.get(target.entity_id) or cell.result(target, Status.REJECTED, detail="no_result")
            if clamped_to is not None and result.clamped_to is None and result.status not in FAILED:
                result = replace(result, clamped_to=clamped_to)
            if ignored and target.domain != "light" and result.detail is None:
                result = replace(result, detail="light_fields_ignored")
            out.append(result)
        return out
