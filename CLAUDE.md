# device_side

Design and delivery plan: `docs/plans/2026-10-23-device-side-repo-plan.md`. Progress to v0.1.0: `TODO.md`; tick items off in the PR that finishes them. Use its glossary's terms in code
and docs; "platform", "backing" and "claim" are retired.

When an action should raise, skip a target, or what its response holds: match core, per `docs/action-behavior.md`.

**The repo is public:** no household entity IDs, device names, MACs or hostnames anywhere in it, commit messages included.

**No personal tooling:** deploy hosts, SSH aliases, and private stacks belong in gitignored files (`.env.rig`, `notes/`, `CLAUDE.local.md`), not in committed code, docs or commit messages.

## Release flag

`experimental=True` on an adapter's `AdapterScope` keeps it out of a stable release: `cut-release` fails while any
adapter has it (`scripts/check_release.py --release`). Every adapter module needs ≥95% line coverage, experimental or
not; CI checks it.

**Setting it:** for a new action, field or attribute, or integration (including ports), and for a behavior change to
a released adapter that the rig can't exercise. Leave it off for refactors, performance work and fixes the rig run
before each RC covers. When unsure, ask.

**Clearing it:** a PR citing a passing bench record (`docs/bench/<integration>/<action>*.md`) or tester issue that
covers the adapter's whole scope: `AdapterScope.domains`, `.capabilities`, `.fields`, and each of `.options` on and off.

**Proof follows the call.** A record proves the call an adapter sends and the capability it reaches (Shelly: the RPC
component), whatever entity domain the target shows: a relay exposed as a `switch` or an on/off `light` rides one
record. A capability or field nobody has tested is left out of scope and refused, never added on a sibling's proof.

## Pull requests

- Base: whichever is newer, `main` or the latest `release/vX.Y.Z` branch.
- Setup: `uv sync`. Test dependencies live in the `dev` group of `pyproject.toml`; never `uv pip install` into `.venv`, as the next sync removes it.
- Before each push: `.venv/bin/pytest` and `pre-commit run --all-files` (ruff and the household check).
- Before opening the PR: `/audit-code` on the diff, then fix its findings and carry on to the PR; stop for Jason
  only on a big judgment call. Judge each finding by the codebase's long-term health, not the PR's convenience:
  fix it now unless it is genuinely out of scope, and then say where it is tracked.

## Layout

- `custom_components/device_side/core/`: registry, resolver, dispatcher, action registration
- `custom_components/device_side/actions/`: one module per action
- `custom_components/device_side/integrations/<integration>/`: one adapter module per action
- `tests/{core,actions,integrations,rig}`: mirror the above; `rig/` drives the live HA, only via `scripts/rig.py`
- `scripts/`: rig runner, household check, deploy, release checks (coverage and the release flag, tags, RC audits)
- `docs/bench/<integration>/`: bench records. Design detail lives in the repo plan.

## Conventions

- Async throughout; `_LOGGER = logging.getLogger(__name__)`; actions registered once in `async_setup`.
- American English, matching HA. The version lives in `manifest.json`.
