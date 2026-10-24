# Contributing

Device Side grows one adapter at a time: one feature on one platform, in
`custom_components/device_side/platforms/<platform>/<feature>.py`.

Every adapter is tested on real hardware before release, because mocks miss what devices really
do. If you write an adapter for hardware you don't own, someone who owns it can test it.

- **Run the tests:** `uv sync`, `uv pip install -r requirements_test.txt`, then `.venv/bin/pytest`.
- **Test on hardware:** [docs/contributing/rig.md](docs/contributing/rig.md).
- **Before a PR:** `pre-commit run --all-files`. PRs go to the current `release/vX.Y.Z` branch,
  not `main`.

Fuller guides for writing adapters and reporting tests are on the way.
