# Testing on your own Home Assistant

The rig runs integration tests against the maintainer's live hardware. If you want to test a
pre-release on your own setup, here is what to do.

## Install

Copy `custom_components/device_side` into your Home Assistant config directory, or add
`https://github.com/jasonmx/device-side` as a custom HACS repository and install Device Side
from there. Restart Home Assistant.

Add the integration: Settings > Devices & services > Add integration > Device Side. Check that
it appears as loaded with no errors in Settings > System > Logs.

## Try the actions

Open Developer tools > Actions and find `device_side.turn_on_for`. Select only a switch entity:
the brightness, color and transition fields should hide. Add a dimmable light: they should show.

Run the action with a short duration (5-8 seconds) and check the device responds.

## Report

[Open a test report issue](https://github.com/jasonmx/device-side/issues/new?template=test-report.yml)
with the Device Side version, the integration (Shelly, ZHA, etc.), the entity type, the fields
you tested, and whether each action worked. Include any error messages from the logs.
