"""Registry building: guarded platform import, adapter validation, matrix iteration."""

import pytest

from custom_components.device_side import features
from custom_components.device_side.core.registry import AdapterRegistry

from ..conftest import FAKE_PLATFORMS


def test_broken_platform_is_recorded_unavailable_and_others_load():
    registry = AdapterRegistry(features.discover(), FAKE_PLATFORMS)

    broken = registry.platforms["broken_platform"]
    assert not broken.available
    assert "fakelib" in broken.unavailable_reason
    assert [info.key for info in registry.available_platforms()] == ["fake", "fake_special"]
    assert registry.adapter("turn_on_for", "fake").platform == "fake"


def test_matrix_lists_every_pair_sorted():
    registry = AdapterRegistry(features.discover(), FAKE_PLATFORMS)

    assert [(feature, platform, adapter is not None) for feature, platform, adapter in registry.matrix()] == [
        ("turn_off_for", "broken_platform", False),
        ("turn_off_for", "fake", True),
        ("turn_off_for", "fake_special", False),
        ("turn_on_for", "broken_platform", False),
        ("turn_on_for", "fake", True),
        ("turn_on_for", "fake_special", True),
    ]


def test_adapter_for_unknown_feature_is_refused():
    from types import SimpleNamespace

    from ..fakes.fake_platform import PLATFORM, FakeTurnOnFor

    class Stray(FakeTurnOnFor):
        feature = "no_such_feature"

    with pytest.raises(ValueError, match="unknown feature"):
        AdapterRegistry(features.discover(), [SimpleNamespace(PLATFORM=PLATFORM, ADAPTERS=[Stray])])


def test_production_discovery_imports_cleanly():
    registry = AdapterRegistry.discover()
    assert set(registry.features) == {"turn_off_for", "turn_on_for"}
    assert registry.platforms["shelly"].available
    assert registry.adapter("turn_on_for", "shelly") is not None
    assert registry.adapter("turn_off_for", "shelly") is not None
