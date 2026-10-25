# Hue · set_scene

| | |
|---|---|
| Result | pass |
| Date | 2026-10-25 |
| Source | rig run (`scripts/rig.py`), commit `f0d49e5` |
| Fingerprint | `058ccd944ae55ec5` (`integrations/hue/set_scene.py`) |
| Home Assistant | 2026.10.2 |
| Device | Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `sets_while_off[scene]` | `scene` (scene) | pass |
| `applies_while_on[scene]` | `scene` (scene) | pass |
| `no_stale_snapshot[scene]` | `scene` (scene) | pass |
