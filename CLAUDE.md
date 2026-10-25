# device_side

Design and delivery plan: `docs/plans/2026-10-23-device-side-repo-plan.md`. Use its glossary's terms in code
and docs; "platform", "backing" and "claim" are retired.

**The repo is public:** no household entity IDs, device names, MACs or hostnames anywhere in it, commit messages included.

**No personal tooling:** deploy hosts, SSH aliases, and private stacks belong in gitignored files (`.env.rig`, `notes/`, `CLAUDE.local.md`), not in committed code, docs or commit messages.

## Tiers

A tier belongs to an **adapter** (action × integration) and covers its whole scope
(`AdapterScope.domains`, `.capabilities` and `.fields`).

| Tier | Meaning | Bar |
|---|---|---|
| experimental | design in flux | `experimental=True` on the adapter; no coverage bar |
| untested | design settled | >95% coverage of the adapter module; some of its scope not yet covered by a bench record |
| beta | tested on hardware | every capability and field in scope covered by a bench record (rig run or tester report) with the current fingerprint |
| stable | released | on `main`; everything on `main` is stable |

Only `experimental` is declared; `scripts/check_tiers.py` computes the rest and fails on scope no
current-fingerprint record covers. Fingerprint = AST hash of the adapter module, excluding
docstrings and the `AdapterScope` declaration; any other change resets the adapter to
`untested`. Regressions block promotion; they never demote.

**Proof follows the call.** A bench record proves the call an adapter sends and the capability it
reaches (Shelly: the RPC component), whatever entity domain the target shows: a relay exposed as a
`switch` or an on/off `light` rides one record. Records list the capabilities and fields they
exercised. A capability or field nobody has tested is left out of scope and refused, never added on
a sibling's proof. Adding one after a tester report is a scope edit plus a record listing it;
existing records survive because the fingerprint excludes the declaration.

**Setting `experimental`:** set it for a new action, a new field or attribute, or a new integration
(including ports). Leave it off for fixes, refactors and performance work. When unsure, ask.

## Pull requests

- Base: whichever is newer, `main` or the latest `release/vX.Y.Z` branch.
- Setup: `uv sync`, then `uv pip install -r requirements_test.txt`.
- Before each push: `.venv/bin/pytest` and `pre-commit run --all-files` (ruff and the household check).
- Before opening the PR: `/audit-code` on the diff.

## Layout

- `custom_components/device_side/core/`: registry, resolver, dispatcher, action registration
- `custom_components/device_side/actions/`: one module per action
- `custom_components/device_side/integrations/<integration>/`: one adapter module per action
- `tests/{core,actions,integrations,rig}`: mirror the above; `rig/` drives the live HA, only via `scripts/rig.py`
- `scripts/`: rig runner, household check, deploy
- `docs/bench/<integration>/`: bench records. Design detail lives in the repo plan.

## Conventions

- Async throughout; `_LOGGER = logging.getLogger(__name__)`; actions registered once in `async_setup`.
- American English, matching HA. The version lives in `manifest.json`.
