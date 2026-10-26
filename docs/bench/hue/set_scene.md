# Hue · set_scene

| | |
|---|---|
| Result | pass |
| Date | 2026-10-26 |
| Source | rig run (`scripts/rig.py`), commit `b7f2228` |
| Fingerprint | `1e98bc38a24d368c` (`integrations/hue/set_scene.py`) |
| Home Assistant | 2026.10.2 |
| Device | Zone, firmware `unknown` |
| Capabilities | every capability the adapter addresses |
| Fields | none |

## Tests

| Test | Target | Result |
|---|---|---|
| `sets_while_off[scene]` | `scene` (scene) | pass |
| `sets_while_off[scene] observed` | `scene` (scene) | pass |
| `applies_while_on[scene]` | `scene` (scene) | pass |
| `applies_while_on[scene] observed` | `scene` (scene) | pass |
| `no_stale_snapshot[scene] observed` | `scene` (scene) | pass |
