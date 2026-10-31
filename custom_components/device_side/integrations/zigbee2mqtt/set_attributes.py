"""Zigbee2MQTT set_attributes: MoveTo commands with the ExecuteIfOff override through Z2M's generic `command` payload,
so a light that is off stores the values and stays off; then a live read of what was written, which also puts the
values into Z2M's state, and so HA's."""

from typing import ClassVar

from homeassistant.core import HomeAssistant

from .addressing import state_topic, topic
from .bridge import publish
from .members import member_lights
from .read import Reader, reader
from ...actions.set_attributes import SetAttributesRequest
from ...core.adapter import Adapter
from ...core.dispatcher import EMPTY_GROUP
from ...core.models import EntityResult, Status, Target
from ...core.scope import AdapterScope
from ...core.zcl_write import (
    Command,
    MoveToColor,
    MoveToColorTemp,
    MoveToHueAndSaturation,
    MoveToLevel,
    clamp_mireds,
    commands,
    wants_level,
)

# 0.4 s, the Hue bridge's default write fade, as on ZHA; a light that is off doesn't fade. The override sets
# ExecuteIfOff for this command only, so the light takes it while off; Options stays untouched.
_EXECUTE_IF_OFF = {"transtime": 4, "optionsMask": 1, "optionsOverride": 1}

_LEVEL, _COLOR = "genLevelCtrl", "lightingColorCtrl"
NOT_STORED = "not_stored"


def _wire(command: Command) -> dict:
    """The command as Z2M's generic `command` payload, with zigbee-herdsman's names, the fade and the override."""
    match command:
        case MoveToLevel(level):
            cluster, name, params = _LEVEL, "moveToLevel", {"level": level}
        case MoveToColorTemp(mireds):
            cluster, name, params = _COLOR, "moveToColorTemp", {"colortemp": mireds}
        case MoveToColor(x, y):
            cluster, name, params = _COLOR, "moveToColor", {"colorx": round(x * 65535), "colory": round(y * 65535)}
        case MoveToHueAndSaturation(hue, saturation):
            cluster, name, params = _COLOR, "moveToHueAndSaturation", {"hue": hue, "saturation": saturation}
    return {"command": {"cluster": cluster, "command": name, "payload": {**params, **_EXECUTE_IF_OFF}}}


def _kept_level(level: int) -> dict:
    """Z2M's own brightness payload with the state kept (null), so the next plain on comes on at the level written.

    After an off with a transition, Z2M keeps the level from before it and restores it on the next on that carries no
    brightness; a raw command doesn't touch what it keeps. This payload replaces the kept level and sends a MoveToLevel
    without the override, which a light that is off ignores, so it stays off (probe 13j, either hue_native_control).
    """
    return {"state": None, "brightness": level, "transition": 0.4}


def _modes(target: Target) -> set[str]:
    # supported_color_modes stays in the state while the light is off.
    return set((target.state and target.state.attributes.get("supported_color_modes")) or ())


def _attrs(target: Target) -> dict:
    return dict(target.state.attributes) if target.state else {}


def _expected(light: Target, sent: list[Command]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """The clusters to read back from this light, and the attributes that must read as written.

    A light reads back only what it takes: a group member without color temperature ignores a groupcast one. Color
    is read, to refresh HA, but not compared: the bulb clamps it to its gamut.
    """
    modes = _modes(light)
    reads: dict[str, list[str]] = {}
    expected: dict[str, int] = {}
    for command in sent:
        match command:
            case MoveToLevel(level) if modes - {"onoff"}:
                reads[_LEVEL] = ["currentLevel"]
                expected["currentLevel"] = level
            case MoveToColorTemp(mireds) if "color_temp" in modes:
                reads[_COLOR] = ["colorMode", "colorTemperature"]
                expected["colorTemperature"] = clamp_mireds(mireds, _attrs(light))
            case MoveToColor() | MoveToHueAndSaturation() if "xy" in modes:
                reads[_COLOR] = ["colorMode", "currentX", "currentY"]
            case MoveToColor() | MoveToHueAndSaturation() if "hs" in modes:
                reads[_COLOR] = ["colorMode", "currentHue", "currentSaturation"]
    return reads, expected


async def _stored(reading: Reader, light: Target, sent: list[Command]) -> bool:
    """Whether the light reads back the level and color temperature written; raises when a read fails."""
    reads, expected = _expected(light, sent)
    attributes: dict = {}
    for cluster, names in reads.items():
        attributes |= await reading.read_cluster(light, cluster, names)
    return all(attributes[name] == value for name, value in expected.items())


class Z2MSetAttributes(Adapter[SetAttributesRequest]):
    """Publish each MoveTo command to the light or group, never the WithOnOff variants, then read the lights back.

    The ExecuteIfOff override makes a light that is off store the values and stay off (probe 13a). Z2M publishes no
    state after a raw command, so each written cluster is read live from each light, which answers with the target
    even mid-fade (probe 13j): Z2M takes the values from the reply, as from a report, and HA follows. A light whose
    level or color temperature doesn't read back as written ignored the override, and is rejected with not_stored. A
    read that fails raises, so the call raises targets_failed.

    A group is one groupcast per command, and is confirmed only when every member is. min/max_brightness alone clamps
    each member from its own level, so each member gets its own commands, as Hue writes a room light by light. A
    field the light can't take is dropped and the result says so.
    """

    action: ClassVar[str] = "set_attributes"
    integration: ClassVar[str] = "zigbee2mqtt"
    scope: ClassVar[AdapterScope] = AdapterScope(
        experimental=True,
        domains=frozenset({"light"}),
        fields=frozenset(
            {"brightness", "color_temp_kelvin", "hs_color", "rgb_color", "xy_color", "min_brightness", "max_brightness"}
        ),
        confirmable=True,
        native_groups=True,  # read back through its members, which only Z2M's bridge/groups knows
    )

    def supports(self, hass: HomeAssistant, request: SetAttributesRequest, target: Target) -> str | None:
        if (reason := super().supports(hass, request, target)) is not None:
            return reason
        if topic(target, "set") is None or (not target.is_group and state_topic(target) is None):
            return "not_addressable"
        return None

    async def execute(
        self, hass: HomeAssistant, request: SetAttributesRequest, targets: list[Target]
    ) -> list[EntityResult]:
        async def write(target: Target) -> EntityResult:
            lights = await member_lights(hass, target) if target.is_group else [target]
            if not lights:
                return self.result(target, Status.UNSUPPORTED, detail=EMPTY_GROUP)
            async with reader(hass, lights) as reading:
                if target.is_group and wants_level(request, _modes(target)):
                    # One after another inside the group's own task: gathering them would nest the concurrency limits.
                    writes = [await self._write(hass, reading, request, light, [light]) for light in lights]
                else:
                    writes = [await self._write(hass, reading, request, target, lights)]
            sent = any(was_sent for was_sent, _stored, _dropped in writes)
            dropped = any(was_dropped for _sent, _stored, was_dropped in writes)
            detail = "fields_dropped" if dropped else None
            if not sent:
                return self.result(target, Status.UNCHANGED, detail=detail or "within_limits")
            if not all(stored for _sent, stored, _dropped in writes):
                return self.result(target, Status.REJECTED, detail=NOT_STORED)
            return self.result(target, Status.CONFIRMED, detail=detail)

        return await self.gather(hass, targets, write)

    async def _write(
        self, hass: HomeAssistant, reading: Reader, request: SetAttributesRequest, to: Target, lights: list[Target]
    ) -> tuple[bool, bool, bool]:
        """Publish to `to` the commands for its own state, then read them back from `lights`.

        Returns whether anything was sent, whether every light stored it, and whether a field was dropped.
        """
        modes = _modes(to)
        current_level = None
        if wants_level(request, modes) and (current_level := await reading.level(to)) is None:
            # Off, and Z2M has never seen its brightness: there is no level to clamp.
            raise LookupError(f"Zigbee2MQTT has no brightness for {to.entity_id}")
        sent, dropped = commands(request, modes, _attrs(to), current_level)
        if not sent:
            return False, True, dropped
        for command in sent:
            await publish(hass, topic(to, "set"), _wire(command))
        if (level := next((c.level for c in sent if isinstance(c, MoveToLevel)), None)) is not None:
            await publish(hass, topic(to, "set"), _kept_level(level))
        stored = [await _stored(reading, light, sent) for light in lights]
        return True, all(stored), dropped
