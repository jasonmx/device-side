"""Every discovered feature has a block in services.yaml, strings.json and icons.json, and nothing else does."""

import json
from pathlib import Path

import pytest
import yaml

from custom_components.device_side.features import discover

PACKAGE = Path(__file__).parents[2] / "custom_components" / "device_side"


def _load_json(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text())


FEATURES = discover()
FEATURE_KEYS = {feature.key for feature in FEATURES}
# Dot-prefixed keys are YAML anchors for shared filters (the light/services.yaml convention), not services.
_RAW_SERVICES = yaml.safe_load((PACKAGE / "services.yaml").read_text()) or {}
SERVICES_YAML = {key: block for key, block in _RAW_SERVICES.items() if not key.startswith(".")}
STRINGS = _load_json("strings.json")


def test_services_yaml_matches_features():
    assert set(SERVICES_YAML) == FEATURE_KEYS


def test_strings_match_features():
    assert set(STRINGS["services"]) == FEATURE_KEYS


def test_icons_match_features():
    assert set(_load_json("icons.json")["services"]) == FEATURE_KEYS


def test_translation_is_a_copy_of_strings():
    assert _load_json("translations/en.json") == STRINGS


@pytest.mark.parametrize("feature", FEATURES, ids=lambda feature: feature.key)
def test_every_field_has_strings(feature):
    fields = {marker.schema for marker in feature.fields}
    assert set(STRINGS["services"][feature.key].get("fields", {})) == fields
