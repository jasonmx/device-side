"""Registry building: guarded integration import, adapter validation, matrix iteration."""

import pytest

from custom_components.device_side import actions
from custom_components.device_side.core.registry import AdapterRegistry

from ..conftest import FAKE_INTEGRATIONS


def test_broken_integration_is_recorded_unavailable_and_others_load():
    registry = AdapterRegistry(actions.discover(), FAKE_INTEGRATIONS)

    broken = registry.integrations["broken_integration"]
    assert not broken.available
    assert "fakelib" in broken.unavailable_reason
    assert [info.key for info in registry.available_integrations()] == ["fake", "fake_special"]
    assert registry.adapter("turn_on_for", "fake").integration == "fake"


def test_matrix_lists_every_pair_sorted():
    registry = AdapterRegistry(actions.discover(), FAKE_INTEGRATIONS)

    assert [(action, integration, adapter is not None) for action, integration, adapter in registry.matrix()] == [
        ("get_attributes", "broken_integration", False),
        ("get_attributes", "fake", False),
        ("get_attributes", "fake_special", False),
        ("set_attributes", "broken_integration", False),
        ("set_attributes", "fake", False),
        ("set_attributes", "fake_special", False),
        ("set_scene", "broken_integration", False),
        ("set_scene", "fake", False),
        ("set_scene", "fake_special", False),
        ("turn_off_for", "broken_integration", False),
        ("turn_off_for", "fake", True),
        ("turn_off_for", "fake_special", False),
        ("turn_on_for", "broken_integration", False),
        ("turn_on_for", "fake", True),
        ("turn_on_for", "fake_special", True),
    ]


def test_adapter_for_unknown_action_is_refused():
    from types import SimpleNamespace

    from ..fakes.fake_integration import INTEGRATION, FakeTurnOnFor

    class Stray(FakeTurnOnFor):
        action = "no_such_action"

    with pytest.raises(ValueError, match="unknown action"):
        AdapterRegistry(actions.discover(), [SimpleNamespace(INTEGRATION=INTEGRATION, ADAPTERS=[Stray])])


def test_production_discovery_imports_cleanly():
    registry = AdapterRegistry.discover()
    assert set(registry.actions) == {"get_attributes", "set_attributes", "set_scene", "turn_off_for", "turn_on_for"}
    assert registry.integrations["shelly"].available
    assert registry.integrations["hue"].available
    assert registry.adapter("turn_on_for", "shelly") is not None
    assert registry.adapter("turn_off_for", "shelly") is not None
