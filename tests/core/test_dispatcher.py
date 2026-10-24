"""End-to-end through registered services, against the fake integrations."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.device_side.core.models import Status, TimedRequest

from ..conftest import call
from ..fixtures.fake import add_fake_entity, add_fake_native_group, add_ha_group, add_switch_as_x, fake_config_entry

pytestmark = pytest.mark.usefixtures("setup_integration")


@pytest.fixture
def fake(hass):
    return fake_config_entry(hass)


async def test_response_shape(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.desk")
    reset_script.outcomes["light.desk"] = Status.CONFIRMED

    response = await call(hass, "turn_on_for", {"entity_id": "light.desk", "duration": 5})

    assert response == {"light.desk": {"status": "confirmed", "integration": "fake"}}
    [(integration, action, request, entity_ids)] = reset_script.calls
    assert (integration, action, entity_ids) == ("fake", "turn_on_for", ["light.desk"])
    assert request.duration_s == 5


async def test_no_response_requested_returns_none(hass, fake):
    add_fake_entity(hass, fake, "light.desk")

    assert await call(hass, "turn_on_for", {"entity_id": "light.desk", "duration": 5}, return_response=False) is None


async def test_duration_is_clamped_and_reported(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.desk")

    response = await call(hass, "turn_on_for", {"entity_id": "light.desk", "duration": 500})

    assert response["light.desk"]["clamped_to"] == 100
    assert reset_script.calls[0][2].duration_s == 100


async def test_mixed_room_reports_each_target_without_raising(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "light.b")
    reset_script.outcomes["light.b"] = RuntimeError("radio busy")

    response = await call(hass, "turn_on_for", {"entity_id": ["light.a", "light.b", "light.ghost"], "duration": 5})

    assert response == {
        "light.a": {"status": "sent", "integration": "fake"},
        "light.b": {"status": "rejected", "integration": "fake", "detail": "error"},
        "light.ghost": {"status": "unsupported", "detail": "not_in_registry"},
    }


async def test_every_target_failing_raises(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.a")
    reset_script.outcomes["light.a"] = Status.REJECTED

    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "turn_on_for", {"entity_id": ["light.a", "light.ghost"], "duration": 5})

    assert err.value.translation_key == "all_targets_failed"
    assert err.value.translation_placeholders == {"summary": "light.a: rejected, light.ghost: not_in_registry"}


async def test_invalid_input(hass, fake):
    add_fake_entity(hass, fake, "light.a")

    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "turn_on_for", {"entity_id": [], "duration": 5})
    assert err.value.translation_key == "no_targets"

    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "turn_on_for", {"entity_id": "light.a", "duration": 0})
    assert err.value.translation_key == "invalid_duration"


async def test_ha_groups_expand_for_light_and_switch(hass, fake, reset_script):
    for entity_id in ("light.a", "light.b", "switch.c"):
        add_fake_entity(hass, fake, entity_id)
    add_ha_group(hass, "light.room", ["light.a", "light.b"])
    add_ha_group(hass, "switch.plugs", ["switch.c"])

    response = await call(hass, "turn_on_for", {"entity_id": ["light.room", "switch.plugs"], "duration": 5})

    assert list(response) == ["light.a", "light.b", "switch.c"]
    assert reset_script.calls[0][3] == ["light.a", "light.b", "switch.c"]


async def test_empty_ha_group_is_unsupported(hass, fake):
    add_fake_entity(hass, fake, "light.a")
    add_ha_group(hass, "light.nobody", [])

    response = await call(hass, "turn_on_for", {"entity_id": ["light.a", "light.nobody"], "duration": 5})

    assert response["light.nobody"] == {"status": "unsupported", "detail": "empty_group"}


async def test_native_group_passes_through_when_adapter_addresses_groups(hass, fake, reset_script):
    add_fake_entity(hass, fake, "switch.a")
    add_fake_native_group(hass, fake, "switch.fake_group", ["switch.a"])

    response = await call(hass, "turn_off_for", {"entity_id": "switch.fake_group", "duration": 5})

    assert list(response) == ["switch.fake_group"]
    assert reset_script.calls[0][3] == ["switch.fake_group"]


async def test_native_group_expands_when_adapter_cannot_address_it(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "light.b")
    add_fake_native_group(hass, fake, "light.fake_group", ["light.a", "light.b"])

    response = await call(hass, "turn_on_for", {"entity_id": ["light.fake_group", "light.a"], "duration": 5})

    assert set(response) == {"light.a", "light.b"}
    assert reset_script.calls[0][3] == ["light.a", "light.b"]


async def test_native_group_without_expand_hook_is_unsupported(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.lamp", identifier="special_1")
    add_fake_entity(hass, fake, "light.special_group", unique_id="group:special", identifier="special_g")

    response = await call(hass, "turn_on_for", {"entity_id": ["light.special_group", "light.lamp"], "duration": 5})

    assert response["light.special_group"] == {
        "status": "unsupported",
        "integration": "fake_special",
        "detail": "group_not_supported",
    }
    assert reset_script.calls == [("fake_special", "turn_on_for", reset_script.calls[0][2], ["light.lamp"])]


async def test_unsupported_reasons_from_adapters(hass, fake):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "light.lamp", identifier="special_1")
    add_fake_entity(hass, fake, "switch.s")

    colored = await call(
        hass, "turn_on_for", {"entity_id": ["light.a", "switch.s"], "duration": 5, "rgb_color": [255, 0, 0]}
    )
    assert colored["light.a"]["detail"] == "fields_not_tested"
    assert colored["switch.s"]["detail"] == "light_fields_ignored"
    assert colored["switch.s"]["status"] == "sent"

    off = await call(hass, "turn_off_for", {"entity_id": ["light.a", "light.lamp", "switch.s"], "duration": 5})
    assert off["light.a"]["detail"] == "domain_not_tested"  # the fake adapter's scope is switches only
    assert off["light.lamp"]["detail"] == "no_adapter"


async def test_wrapper_reports_under_the_light_and_refuses_light_fields(hass, fake, reset_script):
    add_fake_entity(hass, fake, "switch.relay")
    add_switch_as_x(hass, "light.relay", "switch.relay")
    reset_script.outcomes["switch.relay"] = Status.CONFIRMED

    response = await call(hass, "turn_on_for", {"entity_id": "light.relay", "duration": 5})

    assert response == {"light.relay": {"status": "confirmed", "integration": "fake"}}
    assert reset_script.calls[0][3] == ["switch.relay"]

    reset_script.calls.clear()
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "turn_on_for", {"entity_id": "light.relay", "duration": 5, "brightness": 128})
    assert err.value.translation_placeholders["summary"] == "light.relay: fields_not_supported"
    assert reset_script.calls == []


async def test_wrapper_and_its_switch_each_get_a_result(hass, fake, reset_script):
    add_fake_entity(hass, fake, "switch.relay")
    add_switch_as_x(hass, "light.relay", "switch.relay")

    response = await call(hass, "turn_on_for", {"entity_id": ["light.relay", "switch.relay"], "duration": 5})

    assert response == {
        "light.relay": {"status": "sent", "integration": "fake"},
        "switch.relay": {"status": "sent", "integration": "fake"},
    }
    assert reset_script.calls[0][3] == ["switch.relay", "switch.relay"]  # the same Set twice: idempotent


async def test_domain_outside_the_action_is_unsupported(hass, fake):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "cover.blind")

    response = await call(hass, "turn_on_for", {"entity_id": ["light.a", "cover.blind"], "duration": 5})

    assert response["cover.blind"] == {"status": "unsupported", "integration": "fake", "detail": "domain_not_supported"}


async def test_adapter_exception_and_timeout_reject_every_target(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "switch.b")
    reset_script.execute_error = RuntimeError("bridge gone")

    with pytest.raises(HomeAssistantError):
        await call(hass, "turn_on_for", {"entity_id": ["light.a", "switch.b"], "duration": 5})

    reset_script.execute_error = None
    reset_script.delay = 1
    with (
        patch("custom_components.device_side.core.dispatcher.ADAPTER_TIMEOUT_S", 0.01),
        pytest.raises(HomeAssistantError) as err,
    ):
        await call(hass, "turn_on_for", {"entity_id": "light.a", "duration": 5})
    assert err.value.translation_placeholders == {"summary": "light.a: timeout"}


async def test_missing_and_stray_results_are_reconciled(hass, fake):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "light.b")

    async def execute(self, hass, request, targets):
        return [self.result(targets[0], Status.SENT), self.result(targets[0], Status.REJECTED)] + [
            self.result(targets[0], Status.SENT).__class__("light.elsewhere", Status.SENT)
        ]

    with patch("tests.fakes.fake_integration.FakeTurnOnFor.execute", execute):
        response = await call(hass, "turn_on_for", {"entity_id": ["light.a", "light.b"], "duration": 5})

    assert response == {
        "light.a": {"status": "sent", "integration": "fake"},
        "light.b": {"status": "rejected", "integration": "fake", "detail": "no_result"},
    }


async def test_integration_semaphore_bounds_concurrency(hass, fake, reset_script):
    entity_ids = [add_fake_entity(hass, fake, f"light.l{n}") for n in range(6)]
    reset_script.delay = 0.01

    await call(hass, "turn_on_for", {"entity_id": entity_ids, "duration": 5})

    assert reset_script.max_active == 2  # IntegrationInfo.max_concurrency, below the adapter's 4


async def test_adapters_on_different_integrations_run_concurrently(hass, fake, reset_script):
    add_fake_entity(hass, fake, "light.a")
    add_fake_entity(hass, fake, "light.lamp", identifier="special_1")
    reset_script.delay = 0.05

    async with asyncio.timeout(0.09):
        await call(hass, "turn_on_for", {"entity_id": ["light.a", "light.lamp"], "duration": 5})

    assert reset_script.max_active == 2


async def test_calls_refused_until_entry_loads(hass, setup_integration, fake):
    add_fake_entity(hass, fake, "light.a")
    await hass.config_entries.async_unload(setup_integration.entry_id)

    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "turn_on_for", {"entity_id": "light.a", "duration": 5})
    assert err.value.translation_key == "not_loaded"


def test_timed_request_is_what_adapters_see():
    assert TimedRequest(duration_s=1).fields_present() == frozenset()
