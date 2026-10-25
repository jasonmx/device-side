# Contributing

Everybody is invited and welcome to contribute.

We're looking for four kinds of help in particular:

- **Testers.** No coding needed. You just need to have lights or switches on Matter, ZHA, Zigbee2MQTT, Shelly or Hue. You install an experimental pre-release, run a few automations, and tell us what happened. The tests will take 5-15 minutes. A successful test unlocks the feature for other users. Please [open an issue](https://github.com/jasonmx/device-side/issues/new?title=Volunteer%20tester&body=I%27d%20like%20to%20volunteer%20for%20testing.%0A%0AIntegrations%20my%20lights%20and%20switches%20use%3A%0A%0AFeatures%20I%27d%20like%20to%20test%3A%0A) to get in touch, listing the features and integrations you're willing to test.
- **Feature requests.** Tell us which on-device features and integrations you'd most like added next, and why. A Home Assistant Community thread for this is coming shortly after the v0.0.1 release.
- **Bug reports.** If something doesn't look or work right, please [open an issue](https://github.com/jasonmx/device-side/issues/new?body=What%20happened%3A%0A%0AWhat%20I%20expected%3A%0A%0ASteps%20to%20reproduce%3A%0A%0ADevice%20Side%20version%20and%20integration%3A%0A) and let us know.
- **Code.** Add support for a new device capability or integration, or fix a bug. Read
  [What gets built](#what-gets-built) before you start, so your work isn't turned down for scope.

## What gets built

- **On-device features only.** Our goal is to unlock features that already exist on devices and are hard to access in HA. We never simulate features with Home Assistant timers or loops.
- **Features with broad appeal.** We focus on features that users keep asking for in community forums and feature requests, and which are supportable by at least one of the [top-30 Home Assistant integration](https://analytics.home-assistant.io/integrations/). That keeps us focused on the most important features, while keeping the codebase simple and easy to maintain.
- **Gap fillers.** We focus on features that are missing from or really hard to use in HA. We avoid replicating what Core and the automation editor already do well.
- **New integrations and entity domains.** Contributors are welcome to add new integrations (e.g. TP-Link, Z-Wave) and new entity domains (e.g. fans, climate), subject to the broad appeal principle above.
- **Accessible to non-tech users.** We create simple actions that are easily understood. For example, we end dimming transitions with a `stop` action, because `set brightness_step: 0` is not intuitive.

## Developing

- To test on your own Home Assistant, see [docs/contributing/testing.md](docs/contributing/testing.md).
- If you use a coding agent, point it at [CLAUDE.md](CLAUDE.md). It holds the repo's rules.
- Open pull requests against whichever is newer: `main` or the latest `release/vX.Y.Z` branch.
  Just after a release there may be no release branch.
- Set up with `uv sync`. To add a dependency, use `uv add --dev`, not `uv pip install`.
- Run `.venv/bin/pytest` and `pre-commit run --all-files` before you push. CI runs both.
- If you use Claude, run `/audit-code` on your diff before opening a pull request. Else ask for an audit in the PR.
- A new action, field or integration starts with `experimental=True` on its adapter, which waives the coverage bar so you can try things quickly. Fixes and refactors don't set it.
