import asyncio
import logging
from dataclasses import replace

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, State, split_entity_id
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import target as target_helpers

from . import duration
from .action import Action
from .adapter import Adapter
from .errors import TargetNotSupported
from .fields import lacking
from .groups import expand_ha_groups
from .models import FAILED, ActionKind, EntityResult, Request, Status, Target, TimedRequest
from .registry import AdapterRegistry
from .resolver import resolve
from ..const import ADAPTER_TIMEOUT_S, DOMAIN

_LOGGER = logging.getLogger(__name__)

# A group with no members holds nothing to act on, which is not a reason it can't: it is skipped, never raised.
EMPTY_GROUP = "empty_group"
# The config entry behind the target isn't loaded: unavailable, as core treats an entity whose platform isn't up.
NOT_LOADED = "integration_not_loaded"


def _available(state: State | None) -> bool:
    return state is not None and state.state != STATE_UNAVAILABLE


def _skip(entity_id: str, named: bool, reason: str, integration: str | None = None) -> list[EntityResult]:
    """A target that can never take the action: raise if the caller named it, else the result that skips it."""
    if reason == EMPTY_GROUP:
        return []
    if named:
        raise TargetNotSupported(entity_id, reason)
    return [EntityResult(entity_id, Status.UNSUPPORTED, integration=integration, detail=reason)]


class Dispatcher:
    def __init__(self, hass: HomeAssistant, registry: AdapterRegistry):
        self.hass = hass
        self.registry = registry

    async def handle(self, action: type[Action], call: ServiceCall) -> ServiceResponse:
        """Act on every target that can take the action, as core's entity actions do (docs/action-behavior.md).

        A named target that can never take it raises before anything is sent; an indirect one is skipped and logged.
        Unavailable targets are skipped. A device failure raises once every target has run.
        """
        request = replace(action.parse(self.hass, call), context=call.context)
        selection = target_helpers.TargetSelection(call.data)
        if not selection.has_any_target:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_targets")
        # expand_group=False: we expand group.* ourselves so members remember which group they came from.
        selected = target_helpers.async_extract_referenced_entity_ids(self.hass, selection, expand_group=False)
        members, _ = expand_ha_groups(self.hass, sorted(selected.referenced | selected.indirectly_referenced))

        results, targets = self._resolve(action, selected, members)
        if targets:
            results += await action.run(self.hass, request, targets, self)
        order = {entity_id: index for index, entity_id in enumerate(members)}
        results.sort(key=lambda result: order.get(result.entity_id, len(order)))
        return self._respond(action, call, results)

    def _resolve(
        self, action: type[Action], selected: target_helpers.SelectedEntities, members: dict[str, str | None]
    ) -> tuple[list[EntityResult], list[Target]]:
        """The targets to plan, and a skip for each indirect one that resolution already rules out."""
        results: list[EntityResult] = []
        missing: set[str] = set()
        targets: list[Target] = []
        for entity_id, via_group in members.items():
            named = entity_id in selected.referenced
            if split_entity_id(entity_id)[0] not in action.domains:
                # Core's entity actions never see another domain's entities in an area, so only a named one raises.
                if named:
                    raise TargetNotSupported(entity_id, "domain_not_supported")
                continue
            if not _available(self.hass.states.get(entity_id)):
                missing.add(entity_id)
                continue
            target = resolve(self.hass, self.registry, entity_id, via_group)
            if target == NOT_LOADED:
                missing.add(entity_id)
            elif isinstance(target, str):
                results += _skip(entity_id, named, target)
            elif target.domain not in action.domains:
                results += _skip(entity_id, named, "domain_not_supported", target.integration)
            else:
                targets.append(replace(target, named=named))
        selected.log_missing(missing & selected.referenced, _LOGGER)
        return results, targets

    @staticmethod
    def _respond(action: type[Action], call: ServiceCall, results: list[EntityResult]) -> ServiceResponse:
        """Log the skipped targets, raise on a device failure or an empty response, else answer for those that ran."""
        # An empty group is skipped silently, whether planning found it so or an adapter that reads membership did.
        if skipped := [r for r in results if r.status is Status.UNSUPPORTED and r.detail != EMPTY_GROUP]:
            _LOGGER.warning(
                "%s skipped targets that can't take it: %s",
                action.key,
                ", ".join(f"{result.entity_id} ({result.detail})" for result in skipped),
            )
        ran = [result for result in results if result.status is not Status.UNSUPPORTED]
        if failed := [result for result in ran if result.status in FAILED]:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="targets_failed",
                translation_placeholders={
                    "summary": ", ".join(f"{result.entity_id}: {result.detail or result.status}" for result in failed)
                },
            )
        if not call.return_response:
            return None
        if not ran:
            # Core raises here too: the caller asked for data and nothing could give it.
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="no_entities_matched")
        if action.kind is ActionKind.QUERY:
            # Core's shape for data, as weather.get_forecasts returns it: each target's own data under its entity_id.
            return {result.entity_id: result.data or {} for result in ran}
        return {result.entity_id: result.as_response() for result in ran}

    async def run_adapters(self, action_key: str, request: Request, targets: list[Target]) -> list[EntityResult]:
        """Plan every target, then run each adapter once per distinct request, every run concurrently.

        Planning buckets targets by adapter, expands native groups an adapter can't address, drops the fields each
        target lacks and checks supports() on what is left. A named target that can't take the action raises then,
        before anything is sent. Returns a result per target that ran or was left nothing to do, and an unsupported
        one per indirect target skipped.
        """
        results: list[EntityResult] = []
        buckets: dict[str, tuple[Adapter, list[Target]]] = {}
        for target in targets:
            if (adapter := self.registry.adapter(action_key, target.integration)) is None:
                results += _skip(target.reported_id, target.named, "no_adapter", target.integration)
                continue
            buckets.setdefault(target.integration, (adapter, []))[1].append(target)

        runs: list[tuple[Adapter, Request, list[Target], frozenset[str]]] = []
        for adapter, bucket in buckets.values():
            # One execute per set of dropped fields, so every target in a run gets the same request.
            by_dropped: dict[frozenset[str], list[Target]] = {}
            for target in self._expand_native_groups(adapter, bucket, results):
                dropped = lacking(target, request) | (request.fields_present() & adapter.scope.drops)
                reduced = request.without(dropped)
                if reason := adapter.supports(self.hass, reduced, target):
                    results += _skip(target.reported_id, target.named, reason, adapter.integration)
                elif reduced.nothing_to_do():
                    results.append(adapter.result(target, Status.UNCHANGED, detail="fields_dropped"))
                else:
                    by_dropped.setdefault(dropped, []).append(target)
            runs += [(adapter, request.without(dropped), ready, dropped) for dropped, ready in by_dropped.items()]

        for adapter_results in await asyncio.gather(*(self._run_adapter(*run) for run in runs)):
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
                results += _skip(target.reported_id, target.named, "group_not_supported", adapter.integration)
            else:
                # Members are indirect, so an unavailable one is skipped quietly, as core skips one in an area.
                expanded += [member for member in expand(self.hass, target) if _available(member.state)]
        seen: set[str] = set()
        return [target for target in expanded if not (target.reported_id in seen or seen.add(target.reported_id))]

    async def _run_adapter(
        self, adapter: Adapter, request: Request, targets: list[Target], dropped: frozenset[str]
    ) -> list[EntityResult]:
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
        return self._reconcile(adapter, targets, raw, clamped_to, dropped)

    def _reconcile(
        self,
        adapter: Adapter,
        targets: list[Target],
        raw: list[EntityResult],
        clamped_to: float | None,
        dropped: frozenset[str],
    ) -> list[EntityResult]:
        """One result per target: stray ones dropped, missing ones rejected. A run the dispatcher dropped fields
        from says so in detail, unless the adapter gave one."""
        by_id: dict[str, EntityResult] = {}
        expected = {target.reported_id for target in targets}
        for result in raw:
            if result.entity_id in expected and result.entity_id not in by_id:
                by_id[result.entity_id] = result
            else:
                _LOGGER.debug(
                    "%s on %s: dropping stray result for %s", adapter.action, adapter.integration, result.entity_id
                )
        out = []
        for target in targets:
            result = by_id.get(target.reported_id) or adapter.result(target, Status.REJECTED, detail="no_result")
            if result.status not in FAILED:
                if dropped and result.detail is None:
                    result = replace(result, detail="fields_dropped")
                if clamped_to is not None and result.clamped_to is None:
                    result = replace(result, clamped_to=clamped_to)
            out.append(result)
        return out
