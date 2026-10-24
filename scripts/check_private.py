#!/usr/bin/env python3
"""Refuse a commit whose files or message name the household's private details.

The repo is public, so the blocklist cannot live in it. Terms come from the gitignored files that already hold them:
the rig inventory's entity IDs, .env.rig's HA host and token, and .private-terms (one term per line, for names,
hostnames and anything else). Where none of those exist (CI, a contributor's clone) the check passes.

Usage: scripts/check_private.py FILE ...   (pre-commit passes staged files, or the message file at commit-msg)
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.rig.inventory import ENV_FILE, INVENTORY, Inventory, load_env  # noqa: E402

PRIVATE_TERMS = REPO / ".private-terms"
# Hosts the docs and examples name on purpose.
GENERIC_HOSTS = frozenset({"homeassistant.local", "localhost", "127.0.0.1"})


def private_terms(
    inventory: Path = INVENTORY, env_file: Path = ENV_FILE, terms_file: Path = PRIVATE_TERMS
) -> dict[str, str]:
    """Lowercased term -> label to report. Secrets are reported by label, never echoed."""
    terms: dict[str, str] = {}
    if inventory.exists():
        for entities in Inventory.load(inventory).platforms.values():
            terms.update((e.entity_id.lower(), e.entity_id) for e in entities)
    if env_file.exists():
        env = load_env(env_file)
        if (host := urlparse(env.get("HA_URL", "")).hostname) and host not in GENERIC_HOSTS:
            terms[host.lower()] = host
        if token := env.get("HA_TOKEN"):
            terms[token.lower()] = "HA_TOKEN from .env.rig"
    if terms_file.exists():
        for line in terms_file.read_text().splitlines():
            if (line := line.strip()) and not line.startswith("#"):
                terms[line.lower()] = line
    return terms


def find(paths: list[Path], terms: dict[str, str]) -> list[str]:
    hits = []
    for path in paths:
        try:
            lines = path.read_text().splitlines()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for number, line in enumerate(lines, 1):
            lowered = line.lower()
            hits.extend(f"{path}:{number}: {label}" for term, label in terms.items() if term in lowered)
    return hits


def main(argv: list[str]) -> int:
    if not (terms := private_terms()):
        return 0
    if hits := find([Path(arg) for arg in argv], terms):
        print("Private details in a public repo:", *hits, sep="\n  ")
        print("Remove them, or move them to a gitignored file (CLAUDE.local.md, inventory.yaml, .env.rig).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
