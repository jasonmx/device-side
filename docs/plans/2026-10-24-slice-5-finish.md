# Slice 5: what's left before v0.0.1 and the HACS submission

## Context

Slice 5 (`docs/plans/2026-10-23-hacs-early-release.md`) ships v0.0.1 and files the `hacs/default` PR to start
the months-long review. Most of it is already done on `release/v0.0.1`. I checked the remaining steps against
hacs.xyz/docs/publish/include, /integration and the `hacs/default` PR template.

**Already done (checked live):** MIT `LICENSE` (GitHub reports `mit`); `brand/icon.png`, `@2x`, plus dark
variants; repo public, issues on, description set, topics `hacs`, `home-assistant`, `shelly`; `validate.yml`
enabled, nightly schedule restored, guard removed; full-history secrets scan (#12); `CONTRIBUTING.md`;
README with HACS custom-repo install; `hacs.json` has `name`; manifest has all six required keys; the
latest push to `release/v0.0.1` is green on all four workflows (HACS, hassfest, tests, lint).

**Stale:** the two bench records. #7 renamed `platforms/` to `integrations/` and changed both Shelly adapter
modules (`platform` became `integration`, among other renames), so the fingerprints `970267045fd012dc` and
`dcbb54c1d3fd576b` and the cited path `platforms/shelly/...` no longer match. #7's commit message says so too.
The bar for v0.0.1 is beta, so both adapters need a fresh rig run. The `RIG_*_CMD` lines in `.env.rig` are
what that run needs.

## Remaining steps

### 0. Rename the features: "On With Timed Off" / "Off With Timed On" (first, in the step 1 worktree)

`OnWithTimedOff` is the Zigbee/Matter command name, and it says what happens better than "Delayed Off".
Only the feature names change. The action IDs (`turn_on_for`, `turn_off_for`) and the UI action names
("Turn on for") stay as they are.

| Now | Becomes |
|---|---|
| Delayed Off (`turn_on_for`) | On With Timed Off |
| Delayed On (`turn_off_for`) | Off With Timed On |
| "delayed on/off" (generic) | "timed on/off" |
| "the delayed off" / "the delayed on" | "the timed off" / "the timed on" |

Sites (`rg -i "delayed"` found all of them):
- `README.md`: intro line 3, the feature table (below), the `## Delayed on/off` heading, the cancel line 70.
- `custom_components/device_side/strings.json` and `translations/en.json`: the two service descriptions.
- `docs/plans/2026-10-23-device-side-repo-plan.md` line 80, "the delayed flip". Prose only;
  `cancel_delayed_toggle` (lines 84, 599, 650; handoff doc line 161) is a proposed action ID, so it stays.

### 1. Refresh the bench records (worktree `wt/bench-refresh` off `release/v0.0.1`)
1. **Ask Jason before running the rig.** Then `scripts/rig.py --integration shelly` (deploys `origin/wt/bench-refresh`,
   restarts HA and runs both Shelly rig modules). A `--dry-run` comes first to show the plan.
2. Rewrite `docs/bench/shelly/turn_on_for.md` and `turn_off_for.md`: date, HA version, firmware, commit,
   path `integrations/shelly/<action>.py`, and the new fingerprints.
3. Compute the fingerprints with a one-off scratchpad script using the CLAUDE.md definition: sha256 over
   `ast.dump` of the module with docstrings and the `scope = AdapterScope(...)` assignment removed, first
   16 hex digits. First, check that the script reproduces the old hashes on the module at `4dc28b6`, so
   the method matches the one used before.
4. Same PR, small items:
   - README: the 🔒 note says "installing the experimental pre-release from HACS", but no pre-release
     exists. Point it at `CONTRIBUTING.md` (volunteer testers) instead.
   - Add the topic `hacs-integration`, which the slice plan lists (a `gh repo edit` call, not a file change).
   - Redo the README feature table (below).
   - Remove the "issue filed to switch the README install section" step from the slice 5 row of the repo plan
     and from `2026-10-23-hacs-early-release.md`. The my.home-assistant `hacs_repository` badge opens the
     repo in HACS whether or not it's in the default store, so the README needs no change after the PR merges.

#### Feature table

Problems now: five long feature headers wrap, the Shelly cell stacks three lines, the Hue links wrap, and
everything is left-aligned. Fix: transpose the table so features are rows (long labels in one unwrapped
column) and integrations are short column headers. Center the status columns. Move the Hue link to a note.
Put ❌ in the cells the devices can't do, instead of leaving them blank. Roadmap becomes 🔵.

**Bug fixed along the way:** the current table puts Z2M, ZHA and Matter under Delayed On. Their native
command is `OnWithTimedOff` (on, then off after `on_time`), which is `turn_on_for`. `strings.json` calls
that timer "the delayed off", so they belong under **On With Timed Off**. Off With Timed On
(`turn_off_for`) is Shelly-only natively (repo plan, Scope). On With Timed Off goes first because it's the
more useful one.

```markdown
|                        |         Shelly          | Zigbee2MQTT | ZHA | Matter | Hue |
|:---------------------- |:-----------------------:|:-----------:|:---:|:------:|:---:|
| On With Timed Off      | ✨ switches<br>🙋 lights |     🔵      | 🔵  |   🔵   | 🔵  |
| Off With Timed On      | ✨ switches<br>🙋 lights |     ❌      | ❌  |   ❌   | 🔵  |
| Set Turn-On Levels     |           🔵            |     🔵      | 🔵  |   🔵   | 🔵  |
| Hold-to-Dim            |           🔵            |     🔵      | 🔵  |   🔵   | ✅¹ |
| Set Without Turning On |           🔵            |     🔵      | 🔵  |   🔵   | ✅¹ |

✨ New, tested on real hardware · ✅ Released, tested on real hardware · 🙋 Built, needs a volunteer with the device to test it
([help test](CONTRIBUTING.md)) · 🔵 Roadmap · ❌ The devices can't do it

¹ Available now in [Hue Smooth Dimming](https://github.com/jasonmx/hue-smooth-dimming), and moving into Device Side.

Details per integration are in [docs/integrations.md](docs/integrations.md).
```

In the Usage section below the table, list `turn_on_for` first too. It already is, so nothing changes there.

The only line that wraps on purpose is the Shelly cell, and it wraps the same way in both rows. Before
merging, check how it renders on GitHub, both in the PR's rich diff and on the branch's README page.
Also check HACS's README view on the rig during the smoke test.
5. `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff, then PR into `release/v0.0.1`.
   After `ci-green`, squash-merge, then remove the worktree and branch.

Leave the README matrix without `<!-- matrix -->` markers: the feature table in #4 is a different design
from the generated adapter matrix. Slice 8 decides how `gen_docs.py` handles it.

### 2. Release (Jason's steps per `CLAUDE.local.md`; I prepare and wait on CI)
1. Jason opens and merges the PR `release/v0.0.1` → `main`.
2. `WORKFLOW=Validate ci-green` and `ci-green` on `main`: HACS and hassfest must be green **before** the
   release. HACS requires the release to come after the actions pass.
3. Jason tags `v0.0.1` and creates a **full** release (`gh release create v0.0.1 --target main`, not
   `--prerelease`).
4. Optional smoke test (ask first): install as a HACS custom repository on the rig HA. Confirm both
   actions appear and that one `turn_on_for` works on the plug.

### 3. HACS submission (outward-facing; confirm with Jason before opening)
1. Fork `hacs/default` under the personal account `jasonmx` (not an org, so the PR stays editable). Branch
   from `master`.
2. Add `"jasonmx/device-side"` to the `integration` file in sorted position. The `lint sorted` and `lint jq`
   checks fail on bad order or invalid JSON.
3. Open the PR with every part of the template filled in. Link the v0.0.1 release, a passing HACS action
   run with no `ignore` key, and a passing hassfest run, both on the release commit. **Do not request
   reviews**, because the template says that gets the PR closed.
4. Check that the PR's automated checks pass: owner, brands, core-domain conflict, manifest,
   hacs-validation, HACS manifest, archived, releases, license, repository, lint.

### 4. After filing
1. Cut `release/v0.0.2` from `main` and push it.

## Verification
- `gh repo view --json visibility,licenseInfo,repositoryTopics` shows PUBLIC, MIT, four topics.
- `ci-green` on `main` at the release commit; `gh release view v0.0.1 --json isPrerelease` → `false`.
- The `hacs/default` PR's checks are all green.
- The bench records' fingerprints match the script's output for the adapters on `main`.
