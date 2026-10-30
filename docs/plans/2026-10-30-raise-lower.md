# Raise and lower actions: one per attribute and direction

Branch `wt/raise-lower`, worktree `.worktrees/raise-lower`, off `release/v0.0.2`. Agreed with Jason 2026-10-30.

## Decisions

- **Six actions replace `move`, one per attribute and direction**, as HA names its direction actions
  (`cover.open_cover`/`close_cover`/`stop_cover`, `fan.increase_speed`/`decrease_speed`). No action takes a
  direction field, so each limit is labeled for its action, and a call can never ask for two moves.

  | Action | Fields |
  |---|---|
  | `raise_brightness` | `sweep_time`; `limit` "Maximum brightness" (%, 1–100, step 0.2). Turns the light on. |
  | `lower_brightness` | `sweep_time`; `limit` "Minimum brightness" (%, 0–99, step 0.2): "The light turns off at 0 %. Choose 0.4 % or more to keep it on." |
  | `raise_saturation` | `sweep_time`; `limit` "Maximum saturation" (%, 0–100) |
  | `lower_saturation` | `sweep_time`; `limit` "Minimum saturation" (%, 0–100) |
  | `raise_hue` | `sweep_time`. The hue angle increases: red → yellow → green → blue, wrapping at 360°. |
  | `lower_hue` | `sweep_time`. The hue angle decreases: red → magenta → blue → green, wrapping at 360°. |
  | `stop` | None. Halts every raise and lower in flight on the target, whichever attribute. |

  `sweep_time` (s, default 5, min 0.1) is how long a full range takes: 0–100 % brightness or saturation, or one
  turn of the hue wheel. Behavior, responses and details (`at_limit`, `off`, `fields_dropped`, `clamped_to`) are
  today's `move`'s for that attribute, unchanged.
- **`move` is removed.** No release shipped it, so there is no deprecation. Docs describe the new actions as they
  are and don't mention `move`. Dated plans before this one stay as written.
- **Two moves at once are not promised.** Two calls can still overlap (one per attribute); `stop` halts both.
- **Color temperature stays dropped** (`2026-10-28-drop-color-temp-move.md`).
- hue_dimmer's `raise`/`lower` map to `raise_brightness`/`lower_brightness` with the same fields: the migration
  guide says so in one line. No aliases.

## Steps

1. **Actions.** One module per action: `actions/raise_brightness.py` and so on. They share one request
   (`sweep_time`, optional `limit`) and its parse in a shared module (e.g. `actions/ramp.py`), which also holds the
   attribute and direction each action exports; the hue actions have no `limit`. Delete `actions/move.py` and the
   `nothing_to_move` and `limit_without_direction` errors. Update `services.yaml` (brightness actions target Hue and
   MQTT lights; saturation and hue actions MQTT only, until 7c2), `strings.json`, `translations/en.json` and
   `icons.json`.
2. **Hue.** `hue/move.py` becomes `hue/raise_brightness.py` and `hue/lower_brightness.py` over a shared fade module
   (e.g. `hue/fade.py`). Both scopes carry `predicted_state`. `stop`, `report_filter` and the transition cache are
   unchanged apart from names. 7c2 (Hue saturation) later adds `raise_saturation`/`lower_saturation` adapters.
3. **Zigbee2MQTT.** `zigbee2mqtt/move.py` splits into the six action modules over one shared module holding the
   fades, the hue rate, the publish and the end read-backs. `stop` is unchanged apart from names.
4. **Unit tests.** One test module per action under `tests/actions/` and `tests/integrations/{hue,zigbee2mqtt}/`,
   replacing the `test_move.py` files. Shared behavior is tested once, against the shared module. Coverage ≥95 %
   per adapter module.
5. **Rig.**
   - One step file per action: `raise_brightness.yaml`, `lower_brightness.yaml`, `raise_saturation.yaml`,
     `lower_saturation.yaml`, `raise_hue.yaml`, `lower_hue.yaml`, plus `-predicted_state` files for the two
     brightness actions. `move.yaml`'s cases go to the file of their first call; a case that calls another action
     (`raise_after_soft_off`, `ha_change_mid_move`) uses a step-level `action:` for it. Rename cases and comments
     that say "move" (`light_moved_mid_room_move`, `ha_change_mid_move`).
   - `stop*.yaml`: every `action: move` becomes the matching action.
   - Already on this branch: `sample` reads dotted attributes (`hs_color.1`), with a test and `testing.md`. Keep it.
   - Already on this branch, to rework: drop the three combined cases at the end of `move.yaml`. Rewrite the two
     combined `stop.yaml` cases as two calls: `raise_brightness`, then 1 s later `lower_saturation` (or
     `raise_hue`), then `stop` at 3 s, keeping each attribute's halt checks. Recompute the comments, ranges and
     `observe` text for the 1 s offset. Their observed runs wait for the pre-release sweep.
   - Set `rig_seconds` per file. `scripts/rig.py` with every new action plus `--action stop --dry-run` must parse.
6. **Docs.** Replace, don't annotate: each doc describes the new actions as if they had always been there.
   - `docs/integrations.md`, `docs/action-behavior.md`, `docs/contributing/testing.md` (examples), README.
   - Repo plan: the `move` bullet becomes the table above, and the drop-in rule's "move/stop replace raise/lower"
     exception becomes the hue_dimmer name mapping.
   - Bench records: delete `docs/bench/{hue,zigbee2mqtt}/move*.md` once the rig run below has written the new
     ones; `stop*.md` are rewritten by the same run.
   - `TODO.md`: a slice row for this, which must land before 13j's Z2M freeze and the Z2M A60 run. On 13f's line
     (ZHA, `wt/zha-move-stop`, paused): its move adapter splits into these actions when it resumes. That branch also
     edits `_CaseRun.reading` (group means); its merge keeps both changes. 7c2's line: Hue
     `raise_saturation`/`lower_saturation`.
   - Memories that name `move` (`rig-filter-by-action`, `z2m-move-stop-watched-deferred`,
     `hue-reports-end-brightness`, and their `MEMORY.md` lines): use the new action names.
7. **Checks and PR.** `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff, fix findings,
   PR into `release/v0.0.2`. Adapters stay `experimental`.
8. **Rig run, with Jason's go** (not pre-authorized): unattended, the six actions and `stop` on Hue and Z2M, after
   pushing (deploy needs the branch on origin). Commit the records, then `merge-green <n> --squash
   --delete-branch`, backgrounded.
