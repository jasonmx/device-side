# Contributing

Everybody is invited and welcome to contribute.

We're looking for four kinds of help in particular:

- **Testers.** No coding needed. You just need to have lights or switches on Matter, ZHA, Zigbee2MQTT, Shelly or Hue. You install an experimental pre-release, run a few automations, and tell us what happened. The tests will take 5-15 minutes. A successful test unlocks the feature for other users. Please [open an issue](https://github.com/jasonmx/device-side/issues/new?title=Volunteer%20tester&body=I%27d%20like%20to%20volunteer%20for%20testing.%0A%0AIntegrations%20my%20lights%20and%20switches%20use%3A%0A%0AFeatures%20I%27d%20like%20to%20test%3A%0A) to get in touch, listing the features you'd like to test and the integrations your lights and switches use.
- **Feature requests.** Tell us which on-device features and integrations you'd most like added next, and why. A Home Assistant Community thread for this is coming shortly after the v0.0.1 release.
- **Bug reports.** If something doesn't look or work right, please [open an issue](https://github.com/jasonmx/device-side/issues/new?body=What%20happened%3A%0A%0AWhat%20I%20expected%3A%0A%0ASteps%20to%20reproduce%3A%0A%0ADevice%20Side%20version%20and%20integration%3A%0A) and let us know.
- **Code.** Add support for a new device capability or integration, or fix a bug. Read
  [What gets built](#what-gets-built) before you start, so your work isn't turned down for scope.

## What gets built

- **On-device features only.** Our goal is to unlock on-device features that aren't easily available in HA, never faking them with HA-side timers or loops. We build the building blocks; experiences built on top of them, such as blueprints and dashboard cards, belong in their own repos.
- **Focus on features with broad appeal.** An on-device feature needs to be regularly requested by users in forums or on GitHub, and to exist on devices supported by a [top-30 Home Assistant integration](https://analytics.home-assistant.io/integrations/). This keeps development focused on the most important features while keeping the codebase compact to simplify maintenance.
- **Every integration and entity domain is welcome.** We're starting with lights and switches on Matter, ZHA, Zigbee2MQTT and Shelly, and lights on Hue. Once a feature qualifies, any integration can add it (e.g. TP-Link, Z-Wave), and other entity domains (e.g. fans, climate) are welcome too.
- **We build for people, not machines.** We design and name our actions around how people think, not how devices operate. For example, a `stop` action ends a dimming transition, because `brightness_step: 0` is unintuitive.
- **Fill gaps and fix sharp edges.** We don't replicate what Core and the automation editor can already do easily.

## Developing

- To test on your own Home Assistant, see [docs/contributing/testing.md](docs/contributing/testing.md).
- If you use a coding agent, point it at [CLAUDE.md](CLAUDE.md). It holds the repo's rules.
- Open pull requests against whichever is newer: `main` or the latest `release/vX.Y.Z` branch.
  Just after a release there may be no release branch.
- Set up with `uv sync`. To add a dependency, use `uv add --dev`, not `uv pip install`.
- Run `.venv/bin/pytest` and `pre-commit run --all-files` before you push. CI runs both.
- Run `/audit-code` on your diff in Claude Code before opening a pull request. If you don't use it, ask for an audit in the PR.
- A new action, field or integration starts with `experimental=True` on its adapter, which waives the coverage bar so you can try things quickly. Fixes and refactors don't set it.
