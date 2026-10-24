# Move HACS registration up: ship a Shelly-only v0.0.1 after the rig pass

## Context

Getting into HACS's default store takes a PR to `hacs/default`, and HACS says new submissions
"still take months to be reviewed". The repo plan
(`docs/plans/2026-10-23-device-side-repo-plan.md`) files that PR last (slice 12), after the full v1
scope ships. The aim is to start the review clock as soon as Shelly has passed on the rig, by
shipping the smallest release HACS will accept.

**What HACS checks before you can file** (hacs.xyz/docs/publish/include and /integration):
- The repo is public, active, and has issues enabled, a description and at least one topic.
- There is a **full GitHub release**; a tag alone doesn't count.
- The HACS action passes with no errors or ignores, and hassfest passes.
- There is a license GitHub recognises and the OSI approves.
- There is a `brand/icon.png` (or a domain entry in home-assistant/brands).
- `hacs.json` has a `name`, and the manifest has `domain`, `documentation`, `issue_tracker`,
  `codeowners`, `name` and `version`.
- The domain doesn't clash with a core integration.
- The submitter is the owner, filing from a personal account (not an org).

**Where the repo stands:**
- Already OK: description, issues, `hacs.json`, manifest keys.
- Missing: the LICENSE file, the brand icon and topics. The repo is still private, `main` is the
  scaffold only, and there are no `docs/bench/` records yet.

**What you decided:**
- v0.0.1 scopes Shelly to **`switch`** and on/off **`light`** (both the same `Switch.Set` on the `Switch` capability) for `turn_on_for` and `turn_off_for`.
- `toggle_for` is dropped (no use case: HA's `flash` covers a short toggle).
- The 7-day RC soak is **waived for v0.0.1 only**.
- After v0.0.1, releases go incrementally (`v0.0.x`), and one release can carry several integrations
  or actions. The bump to `v0.1.0` happens when the current plan is feature complete **and**
  third-party testers have validated the hardware the rig doesn't have.

## Approach

### 1. Edit the repo plan (`docs/plans/2026-10-23-device-side-repo-plan.md`)

New delivery sequence:

| # | Slice | Change |
|---|---|---|
| 0–2 | as is (done) | none |
| 3 | Rig harness | Unchanged (running in another session). |
| 4 | `turn_off_for` rig pass | Was slice 5. Rig test for `turn_off_for`, so both v0.0.1 actions have bench records. |
| 5 | **v0.0.1 release + HACS submission** | New. Details in section 2. |
| 6 | Z2M `turn_on_for` | Was 4. Work moves to `release/v0.0.2`. |
| 7 | Hue port | Was 6. |
| 8 | Docs generator + templates | Was 9. Must land before the first `v0.0.2` RC. |
| 9 | Bench + tiers + tester flow + RC audit gate | Was 10. Must land before the first `v0.0.2` RC, which is the first RC of the project. |
| 10 | ZHA `turn_on_for` | Was 7. Still waits for ZHA on the rig. |
| 11 | Matter `turn_on_for` | Was 8. Still waits for Matter on the rig. |
| 12 | `v0.1.0` | Replaces old slice 11. Feature complete for this plan, third-party tester reports for the hardware the rig lacks, matrix current. |

`v0.0.x` releases are cut between slices whenever a set of adapters reaches beta. From `v0.0.2`
onward each one goes through the normal rules: RC, 7-day soak, merge.

Other edits in the same file:
- **Repo** bullet: "private until v1 ships" becomes "public from v0.0.1".
- **Versions:** add the `v0.0.x` / `v0.1.0` rule above.
- **Delivery-sequence paragraph:** "the v0.0.1 merge to `main` is the only PR" becomes "each
  release's merge to `main` is its only PR".
- **Old slice 12:** delete it. Its leftover step (switching the README install section once the
  `hacs/default` PR merges) is dropped: the my.home-assistant `hacs_repository` badge opens the
  repo in HACS whether or not it's in the default store.
- **Slice 10 note added earlier today** (re-enable `validate.yml`): move it into the new slice 5.

### 2. New slice 5: v0.0.1 release + HACS submission

Steps on `release/v0.0.1`:
1. **License:** add an MIT `LICENSE`, and confirm GitHub reports `MIT`, not `NOASSERTION`.
2. **Brand icon:** add `custom_components/device_side/brand/icon.png` (256×256 and `icon@2x.png`
   512×512, square, transparent background). Confirm the HACS action accepts that location; if
   not, file the domain with home-assistant/brands.
3. **Scope:** confirm the Shelly adapters' scope is `switch` and on/off `light` only. The light fields stay out of scope
   per the CLAUDE.md Releases rule until a tester reports.
4. **Bench records:** write `docs/bench/shelly/{turn_on_for,turn_off_for}.md` by hand
   from the rig runs (date, HA version, device model, firmware, fingerprint). `gen_docs.py`
   doesn't exist yet, so compute the fingerprints with a short one-off script or by hand.
5. **README:**
   - Pitch.
   - Install as a HACS custom repository (until the default-store PR merges).
   - Hand-written support matrix: Shelly `switch` × three actions, inside the
     `<!-- matrix -->` markers so `gen_docs.py` takes it over later.
   - Link to the Shelly section of `docs/integrations.md`.
6. **Contributor docs:** a short `CONTRIBUTING.md` pointing at `docs/contributing/testing.md`. The full
   guides stay in slice 8.
7. **Before going public:**
   - Run `gitleaks detect` over the whole history; it must be clean (check that
     `.env.rig`/`inventory.yaml` were never committed).
   - Add topics (`home-assistant`, `hacs`, `hacs-integration`, `shelly`).
   - Flip the repo to public.
8. **CI:**
   - Run `gh workflow enable validate.yml`.
   - In `validate.yml`, restore the nightly `schedule` and remove the private-repo `if:` guard.
   - Wait on `ci-green` for the release branch.
9. **Release:**
   - Open the PR `release/v0.0.1` → `main` and merge it.
   - Wait for `ci-green` on `main`, with HACS and hassfest both green.
   - Tag `v0.0.1` and create a **full** GitHub release (not a pre-release).
10. **HACS submission:**
    - Fork `hacs/default` under `jasonmx` and branch from `master`.
    - Add `jasonmx/device-side` alphabetically to `integration`.
    - Open the PR with the template filled in completely and all checks passing.
11. **After filing:**
    - Cut `release/v0.0.2` from `main` for slice 6 onward.

Soak waiver: add a single line under slice 5 in the repo plan ("v0.0.1 ships without an RC soak
to start the HACS review clock; from v0.0.2 the Releases rules apply in full"). CLAUDE.md is not
edited, because the waiver is one-off and CLAUDE.md holds standing rules only.

### Files touched

- `docs/plans/2026-10-23-device-side-repo-plan.md` (sequence, Repo/Versions bullets, slice 5)
- During slice 5: `LICENSE`, `custom_components/device_side/brand/icon.png` (+ `@2x`),
  `README.md`, `CONTRIBUTING.md`, `docs/bench/shelly/*.md`, `.github/workflows/validate.yml`
- Slice 4: `tests/rig/test_shelly_turn_off_for.py`

## Verification

- The HACS action and hassfest are green on `main` at the release commit (`ci-green` on `main`).
- `gh repo view --json visibility,licenseInfo,repositoryTopics` shows PUBLIC, MIT and topics.
- `gh release view v0.0.1` shows a full release with `isPrerelease: false`.
- The `hacs/default` PR's automated checks are all green (owner, brands, releases, manifest,
  hacs-validation, lint).
- Smoke test: install from HACS as a custom repository into the rig HA (ask first), confirm the
  three actions appear and one `turn_on_for` passes on the plug.

## Order of work

Per the planning rule, implement in a **fresh session**:
1. Edit the repo plan (done).
2. Slice 3 rig runs (in progress in another session).
3. Slice 4 (`turn_off_for` rig pass; ask before each run).
4. Slice 5 (release and HACS submission).
