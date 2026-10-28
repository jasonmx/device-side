"""The rig's household entities and connection settings. Shared by scripts/rig.py and the rig engine.

Pure file reading, no HA or pytest imports, so the runner's preflight can load it before anything mutates.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RIG_DIR = Path(__file__).parent
REPO = RIG_DIR.parents[1]


def main_checkout(repo: Path = REPO) -> Path:
    """The main checkout, which holds the gitignored household files for every linked worktree; else `repo`."""
    try:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return repo
    return Path(common).parent


MAIN_CHECKOUT = main_checkout()
INVENTORY = MAIN_CHECKOUT / RIG_DIR.relative_to(REPO) / "inventory.yaml"
ENV_FILE = MAIN_CHECKOUT / ".env.rig"

ROLES = frozenset(
    {"light_onoff", "light_wrapped", "light_dimmable", "light_ct", "light_color", "switch_plug", "group", "scene"}
)

# Seconds either side of a duration within which a device may flip. Zigbee and Matter hop through a mesh.
TOLERANCE_S = {"shelly": 2.0, "hue": 2.0, "zigbee2mqtt": 3.0, "zha": 3.0, "matter": 3.0}

# Seconds after a move ends, or a stop, that an integration's adapters still predict a light's brightness rather
# than read it (Hue: API_SETTLE_SECONDS; Zigbee2MQTT: move.SETTLE_SECONDS). A case waits them out on its lights, so
# it starts from what HA shows.
SETTLE_S = {"hue": 15.0, "zigbee2mqtt": 2.0}


@dataclass(frozen=True, slots=True)
class RigEntity:
    entity_id: str
    roles: frozenset[str]
    powered_by: str | None = None  # the inventory switch this entity draws power through
    members: tuple[str, ...] = ()  # a group's member lights, for a group light without an entity_id attribute


@dataclass(slots=True)
class Inventory:
    integrations: dict[str, list[RigEntity]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = INVENTORY) -> Inventory:
        raw = yaml.safe_load(path.read_text()) or {}
        inventory = cls()
        for integration, entities in raw.items():
            if integration not in TOLERANCE_S:
                raise ValueError(f"{path.name}: unknown integration {integration!r}; use {', '.join(TOLERANCE_S)}")
            inventory.integrations[integration] = []
            for item in entities or []:
                roles = frozenset(item.get("roles", ()))
                if unknown := roles - ROLES:
                    raise ValueError(f"{path.name}: {item['entity_id']} has unknown roles {sorted(unknown)}")
                members = item.get("members", [])
                if not isinstance(members, list) or not all(isinstance(member, str) for member in members):
                    raise ValueError(f"{path.name}: {item['entity_id']} members must be a list of entity IDs")
                members = tuple(members)
                if members and "group" not in roles:
                    raise ValueError(f"{path.name}: {item['entity_id']} lists members but has no group role")
                inventory.integrations[integration].append(
                    RigEntity(item["entity_id"], roles, item.get("powered_by"), members)
                )
        listed = {entity.entity_id for entities in inventory.integrations.values() for entity in entities}
        for entity_id, supply in inventory.power().items():
            if supply not in listed:
                raise ValueError(f"{path.name}: {entity_id} is powered_by {supply}, which the inventory doesn't list")
        return inventory

    def entity(self, integration: str, role: str) -> str | None:
        return next((e.entity_id for e in self.integrations.get(integration, ()) if role in e.roles), None)

    def members(self, integration: str, entity_id: str) -> tuple[str, ...]:
        return next((e.members for e in self.integrations.get(integration, ()) if e.entity_id == entity_id), ())

    def power(self) -> dict[str, str]:
        """Each entity that draws power through another, mapped to its supply, across every integration."""
        return {e.entity_id: e.powered_by for entities in self.integrations.values() for e in entities if e.powered_by}


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """KEY=value lines from .env.rig, overridden by the process environment."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if (line := line.strip()) and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip("\"'")
    for key in (
        "HA_URL",
        "HA_TOKEN",
        "HA_ADMIN_TOKEN",
        "RIG_SYNC_CMD",
        "RIG_STATUS_CMD",
        "RIG_RESTART_CMD",
        "RIG_PAUSE",
        "HUE_BRIDGE_HOST",
        "HUE_APP_KEY",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    return env
