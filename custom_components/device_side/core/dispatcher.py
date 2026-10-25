import asyncio
import logging
from dataclasses import replace

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.service import async_extract_entity_ids

from . import duration
from .action import Action
from .adapter import Adapter
from .groups import expand_ha_groups
from .models import FAILED, EntityResult, Request, Status, Target, TimedRequest
from .registry import AdapterRegistry
from .resolver import resolve
from ..const import ADAPTER_TIMEOUT_S, DOMAIN

_LOGGER = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, hass: HomeAssistant, registry: AdapterRegistry):
        self.hass = hass
        self.registry = registry

    async def handle(self, action: type[Action], call: ServiceCall) -> ServiceResponse:
        request = replace(action.parse(self.hass, call), context=call.context)
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
            elif target.domain not in action.domains:
                early.append(
                    EntityResult(
                        entity_id, Status.UNSUPPORTED, integration=target.integration, detail="domain_not_supported"
                    )
                )
            elif target.via_wrapper and request.fields_present():
                # The caller addressed a light, so light fields are refused, not dropped as they are on a switch.
                early.append(
                    EntityResult(
                        entity_id, Status.UNSUPPORTED, integration=target.integration, detail="fields_not_supported"
                    )
                )
            else:
                targets.append(target)

        results = (await action.run(self.hass, request, targets, self) if targets else []) + early
        order = {entity_id: index for index, entity_id in enumerate([*members, *empty_groups])}
        # A member row follows its group's row.
        results.sort(
            key=lambda result: (
                order.get(result.entity_id, order.get(result.member_of, len(order))),
                result.member_of is not None,
            )
        )

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

    async def run_adapters(self, action_key: str, request: Request, targets: list[Target]) -> list[EntityResult]:
        """Bucket targets by adapter, expand native groups an adapter can't address, run every adapter concurrently.

        Returns exactly one result per (expanded) target, plus any member rows a native_groups adapter reports for
        the groups it addressed.
        """
        results: list[EntityResult] = []
        buckets: dict[str, tuple[Adapter, list[Target]]] = {}
        for target in targets:
            if (adapter := self.registry.adapter(action_key, target.integration)) is None:
                results.append(
                    EntityResult(target.reported_id, Status.UNSUPPORTED, target.integration, detail="no_adapter")
                )
                continue
            buckets.setdefault(target.integration, (adapter, []))[1].append(target)

        runs = []
        for adapter, bucket in buckets.values():
            bucket = self._expand_native_groups(adapter, bucket, results)
            ready = []
            for target in bucket:
                if reason := adapter.supports(self.hass, request, target):
                    results.append(adapter.result(target, Status.UNSUPPORTED, detail=reason))
                else:
                    ready.append(target)
            if ready:
                runs.append(self._run_adapter(adapter, request, ready))

        for adapter_results in await asyncio.gather(*runs):
            results.extend(adapter_results)
        return results

    def _expand_native_groups(
        self, adapter: Adapter, bucket: list[Target], results: list[EntityResult]
    ) -> list[Target]:
        if adapter.scope.native_groups or not any(target.is_group for target in bucket):
            return bucket
        expand = self.registry.integrations[adapter.integration].expand_group
        expanded: list[Target] = []
        for target in bucket:
            if not target.is_group:
                expanded.append(target)
            elif expand is None:
                results.append(adapter.result(target, Status.UNSUPPORTED, detail="group_not_supported"))
            elif members := expand(self.hass, target):
                expanded.extend(members)
            else:
                results.append(adapter.result(target, Status.UNSUPPORTED, detail="empty_group"))
        seen: set[str] = set()
        return [target for target in expanded if not (target.reported_id in seen or seen.add(target.reported_id))]

    async def _run_adapter(self, adapter: Adapter, request: Request, targets: list[Target]) -> list[EntityResult]:
        clamped_to = None
        if isinstance(request, TimedRequest):
            request, clamped_to = duration.clamp(request, adapter.scope.duration)
        try:
            async with asyncio.timeout(ADAPTER_TIMEOUT_S):
                raw = await adapter.execute(self.hass, request, targets)
        except TimeoutError:
            _LOGGER.warning("%s on %s timed out after %ss", adapter.action, adapter.integration, ADAPTER_TIMEOUT_S)
            return [adapter.result(target, Status.REJECTED, detail="timeout") for target in targets]
        except Exception:
            _LOGGER.exception("%s on %s failed", adapter.action, adapter.integration)
            return [adapter.result(target, Status.REJECTED, detail="error") for target in targets]
        return self._reconcile(adapter, request, targets, raw, clamped_to)

    def _reconcile(
        self,
        adapter: Adapter,
        request: Request,
        targets: list[Target],
        raw: list[EntityResult],
        clamped_to: float | None,
    ) -> list[EntityResult]:
        by_id: dict[str, EntityResult] = {}
        member_rows: dict[str, EntityResult] = {}
        expected = {target.reported_id for target in targets}
        groups = {target.reported_id for target in targets if target.is_group} if adapter.scope.native_groups else set()
        for result in raw:
            if result.entity_id in expected and result.entity_id not in by_id:
                by_id[result.entity_id] = result
            elif result.member_of in groups and not (result.entity_id in expected or result.entity_id in member_rows):
                # A member the caller also targeted keeps its own row.
                member_rows[result.entity_id] = result
            else:
                _LOGGER.debug(
                    "%s on %s: dropping stray result for %s", adapter.action, adapter.integration, result.entity_id
                )
        ignored = bool(request.fields_present())
        out = []
        for target in targets:
            result = by_id.get(target.reported_id) or adapter.result(target, Status.REJECTED, detail="no_result")
            if clamped_to is not None and result.clamped_to is None and result.status not in FAILED:
                result = replace(result, clamped_to=clamped_to)
            if ignored and target.domain != "light" and result.detail is None:
                result = replace(result, detail="light_fields_ignored")
            out.append(result)
        return out + list(member_rows.values())
