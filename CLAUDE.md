# device_side

Design and delivery plan: `docs/plans/2026-10-23-device-side-repo-plan.md`.

**The repo is public:** no household entity IDs, device names, MACs or hostnames anywhere in it, commit messages included.

## Tiers

A tier belongs to an **adapter** (feature × platform). Its claims (`AdapterCapabilities.components`
and `supports_fields`) carry the scope, so a tier covers everything the adapter claims.

| Tier | Meaning | Bar |
|---|---|---|
| experimental | design in flux | `experimental=True` on the adapter; no coverage bar |
| untested | design settled | >95% coverage of the adapter module; some claim not yet covered by a bench record |
| beta | tested on hardware | every claimed component and field covered by a bench record (rig run or tester report) with the current fingerprint |
| stable | released | on `main`; everything on `main` is stable |

Only `experimental` is declared; `scripts/gen_docs.py` computes the rest and fails on a claim no
current-fingerprint record covers. Fingerprint = AST hash of the adapter module, excluding
docstrings and the `AdapterCapabilities` declaration; any other change resets the adapter to
`untested`. Regressions block promotion; they never demote.

**Proof follows the call.** A bench record proves the call an adapter sends and the device-side
backing it reaches (Shelly: the RPC component), whatever HA domain the target shows: a relay exposed
as a `switch` or an on/off `light` rides one record. Records list the backings and fields they
exercised. A backing or field nobody has tested is left out of the claims and refused, never claimed
on a sibling's proof. Adding one after a tester report is a claims edit plus a record listing it;
existing records survive because the fingerprint excludes the declaration.

**Setting `experimental`:** set it for a new action, a new field or attribute, or a new platform
(including ports). Leave it off for fixes, refactors and performance work. When unsure, ask.

## Releases

- Work happens on `release/vX.Y.Z`; RCs are tagged `vX.Y.ZrcN` from it and run every tier.
- Merge to `main` and tag `vX.Y.Z` only when every adapter is `beta` and the latest RC has
  soaked 7+ days with no open `regression` issue. A new RC restarts the soak.
- A backing or field nobody can test is not claimed: leave it out of `components`/`supports_fields`,
  and follow the release with a "testers needed" RC.
- Hotfixes for `severity:high` regressions go straight to `main` and keep their tier. Other fixes
  ride the next release branch and re-climb.
- Passing tester reports (GitHub "Test report" issues) become `docs/bench/<platform>/<feature>.md`
  records citing the issue.
