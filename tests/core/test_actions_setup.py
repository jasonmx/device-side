"""Every discovered action has a block in services.yaml, strings.json and icons.json, and nothing else does."""

import json
from pathlib import Path

import pytest
import yaml

from custom_components.device_side.actions import discover
from custom_components.device_side.core.registry import AdapterRegistry

PACKAGE = Path(__file__).parents[2] / "custom_components" / "device_side"


def _load_json(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text())


ACTIONS = discover()
ACTION_KEYS = {action.key for action in ACTIONS}
SERVICES_YAML = yaml.safe_load((PACKAGE / "services.yaml").read_text()) or {}
STRINGS = _load_json("strings.json")


def test_services_yaml_matches_features():
    assert set(SERVICES_YAML) == ACTION_KEYS


def test_strings_match_actions():
    assert set(STRINGS["services"]) == ACTION_KEYS


def test_icons_match_actions():
    assert set(_load_json("icons.json")["services"]) == ACTION_KEYS


def test_translation_is_a_copy_of_strings():
    assert _load_json("translations/en.json") == STRINGS


@pytest.mark.parametrize("action", ACTIONS, ids=lambda action: action.key)
def test_target_filter_lists_exactly_the_integrations_with_an_adapter(action):
    registry = AdapterRegistry.discover()
    with_adapter = {
        registry.integrations[integration].ha_domain
        for key, integration, adapter in registry.matrix()
        if key == action.key and adapter is not None
    }
    listed = {entry["integration"] for entry in SERVICES_YAML[action.key]["target"]["entity"]}
    assert listed == with_adapter


@pytest.mark.parametrize("action", ACTIONS, ids=lambda action: action.key)
def test_every_field_has_strings(action):
    fields = {marker.schema for marker in action.fields}
    assert set(STRINGS["services"][action.key].get("fields", {})) == fields
