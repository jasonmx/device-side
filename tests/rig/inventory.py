"""The rig's household entities and connection settings. Shared by scripts/rig.py and the rig fixtures.

Pure file reading, no HA or pytest imports, so the runner's preflight can load it before anything mutates.
"""

import ast
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
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return repo
    return Path(common).parent


MAIN_CHECKOUT = main_checkout()
INVENTORY = MAIN_CHECKOUT / RIG_DIR.relative_to(REPO) / "inventory.yaml"
ENV_FILE = MAIN_CHECKOUT / ".env.rig"

ROLES = frozenset(
    {"light_onoff", "light_wrapped", "light_dimmable", "light_ct", "light_color", "switch_plug", "group", "scene"}
)

# Seconds either side of a duration within which a device may flip. Zigbee and Matter hop through a mesh.
TOLERANCE_S = {"shelly": 2.0, "hue": 2.0, "z2m": 3.0, "zha": 3.0, "matter": 3.0}


@dataclass(frozen=True, slots=True)
class RigEntity:
    entity_id: str
    roles: frozenset[str]


@dataclass(slots=True)
class Inventory:
    integrations: dict[str, list[RigEntity]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = INVENTORY) -> Inventory:
        raw = yaml.safe_load(path.read_text()) or {}
        inventory = cls()
        for integration, entities in raw.items():
            inventory.integrations[integration] = []
            for item in entities or []:
                roles = frozenset(item.get("roles", ()))
                if unknown := roles - ROLES:
                    raise ValueError(f"{path.name}: {item['entity_id']} has unknown roles {sorted(unknown)}")
                inventory.integrations[integration].append(RigEntity(item["entity_id"], roles))
        return inventory

    def entity(self, integration: str, role: str) -> str | None:
        return next((e.entity_id for e in self.integrations.get(integration, ()) if role in e.roles), None)


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """KEY=value lines from .env.rig, overridden by the process environment."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if (line := line.strip()) and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip("\"'")
    for key in ("HA_URL", "HA_TOKEN", "RIG_SSH", "RIG_SYNC_CMD", "RIG_STATUS_CMD", "RIG_RESTART_CMD"):
        if key in os.environ:
            env[key] = os.environ[key]
    env.setdefault("RIG_SSH", "ha")
    return env


@dataclass(frozen=True, slots=True)
class RigModule:
    """One rig test module, read without importing it: test_<integration>_<action>.py with literal constants."""

    path: Path
    integration: str
    action: str
    roles: tuple[str, ...]
    seconds: int


def rig_modules(rig_dir: Path = RIG_DIR) -> list[RigModule]:
    # Only plain module-level `NAME = <literal>` assignments count; `ROLES += [...]` is not read.
    modules = []
    for path in sorted(rig_dir.glob("test_*.py")):
        integration, _, action = path.stem.removeprefix("test_").partition("_")
        constants = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"ROLES", "RIG_SECONDS"}
        }
        if missing := {"ROLES", "RIG_SECONDS"} - constants.keys():
            raise ValueError(f"{path.name}: missing module-level constant(s) {sorted(missing)}")
        modules.append(RigModule(path, integration, action, tuple(constants["ROLES"]), constants["RIG_SECONDS"]))
    return modules
