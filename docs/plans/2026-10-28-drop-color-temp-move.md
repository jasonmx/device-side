# Drop color temperature moves (Hue and the action)

## Context

13i's watched tests (`docs/plans/2026-10-28-z2m-move-stop.md`) showed that no halt of a color temperature fade on a
Hue bulb avoids a visible jump. That covered ZCL's stops, a write, and the Hue bridge's own stop. Brightness stops are
clean. So **color temperature moves are dropped on every integration**: the `move` action loses `color_temp`,
`color_temp_limit` and `WARMER`/`COOLER`, so the UI offers nothing that can't work, and Hue stops moving color
temperature. ZHA's `move`/`stop` (13f) follows in its own PR, for brightness, saturation and hue.

## Steps

1. **Action** `actions/move.py`: remove `color_temp` from `DIRECTIONS` and `LIMITS`, `WARMER`/`COOLER`,
   `color_temp_limit` and its validator, and the docstring mention. Do the same in `services.yaml`, `strings.json`
   and `translations/en.json`. A call that passes `color_temp` now fails schema validation.
2. **Hue** `hue/move.py`: scope fields become `{"brightness", "brightness_limit"}`. Remove `color_temp_fade`,
   `tunable`, `light_mirek`, the color temperature branch of `fade_write`, and `lacked`'s color temperature half.
   Rewrite the class docstring.
   - `hue/stop.py`: remove the color temperature stop and its halt from `halts` and `stop_write`.
   - `hue/transition_cache.py`: remove `MIN_MIREK_STEP` if nothing else uses it.
   - `hue/report_filter.py` and `attributes.py`: keep color temperature report handling only where get/set
     attributes still need it. Delete what only the CT move used (check with `rg COLOR_TEMP`).
   - `core/transition.py`: remove `COLOR_TEMP` if nothing uses it any more.
3. **Z2M**: delete the "Color temperature is left out" scope comment, which now has nothing to explain, and any
   `color_temp` refusal test that no longer compiles.
4. **Tests**: delete the Hue color temperature move/stop tests. Add one action test showing `color_temp` is
   rejected by the schema.
5. **Rig**: delete `warmer_stop_warmer` and the combined brightness + color temperature move from
   `tests/rig/steps/move.yaml`/`stop.yaml`, plus the header line "Zigbee2MQTT doesn't move color temperature".
6. **Docs**:
   - `docs/integrations.md`: Hue loses CT move/stop. Add one line under move: no integration moves color
     temperature, because every halt of a Hue bulb's CT fade jumps visibly (13i's watched tests).
   - README feature table: the color temperature move cells.
   - Bench records `docs/bench/hue/move*.md` and `stop*.md`: add a note that the color temperature rows prove a
     call no longer offered. Don't delete the history.
   - The slice plan's "Move attributes on Zigbee" line, the 13f row, and the 7c2 row (saturation only).
   - The repo plan's `move` bullet (directions table).
   - `docs/plans/2026-10-27-hue-move-color.md`: a superseded note at the top of 7c1.
   - `TODO.md`: a line under Done.
7. **Land**: run `.venv/bin/pytest` and `pre-commit run --all-files`, then `/audit-code`, then a PR.
   `merge-green <n> --squash --delete-branch` in the background. No rig run is needed: it only removes a
   capability. Run `rig.py --action move --action stop --dry-run` to check the step files still parse.
