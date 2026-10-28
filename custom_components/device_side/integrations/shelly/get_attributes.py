"""Shelly get_attributes: on/off timer, brightness, color temperature and color from one <Component>.GetStatus."""

from datetime import datetime
from typing import ClassVar

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.color import color_RGB_to_hs, color_RGB_to_xy

from .addressing import address, unsupported_reason
from .rpc import get_status
from ...core.adapter import Adapter
from ...core.models import EntityResult, Request, Status, Target
from ...core.scope import AdapterScope
from ...core.timer import timer_row


def status_row(component: str, status: dict, now: datetime) -> dict:
    """One target's row from its GetStatus. The bulb keeps brightness, ct and rgb while off, so they read then too.

    The time left is the device's timer_started_at against HA's clock: both are SNTP-synced, and the clamp to
    [0, duration] bounds any skew.
    """
    row: dict = {}
    if component == "RGBCCT":
        # Brightness is the device's percent, as Hue's row is. The status carries ct and rgb in either mode; only
        # the active one is reported, as core does.
        row["brightness"] = status["brightness"]
        if status["mode"] == "cct":
            row["color_temp_kelvin"] = status["ct"]
        elif status["mode"] == "rgb":
            rgb = status["rgb"]
            row["rgb_color"] = list(rgb)
            row["hs_color"] = list(color_RGB_to_hs(*rgb))
            row["xy_color"] = list(color_RGB_to_xy(*rgb))
    if "timer_started_at" in status and "timer_duration" in status:
        duration = status["timer_duration"]
        remaining = min(max(status["timer_started_at"] + duration - now.timestamp(), 0), duration)
        row["timer"] = timer_row("off" if status["output"] else "on", remaining, now)
    return row


class ShellyGetAttributes(Adapter[Request]):
    """One GetStatus per target; a device error raises."""

    action: ClassVar[str] = "get_attributes"
    integration: ClassVar[str] = "shelly"
    scope: ClassVar[AdapterScope] = AdapterScope(
        domains=frozenset({"light", "switch"}),
        # A relay shown as a light sends the same Switch.GetStatus; Light, CCT, RGB and RGBW wait for a tester's
        # report.
        capabilities=frozenset({"Switch", "RGBCCT"}),
        confirmable=True,
    )

    def supports(self, hass: HomeAssistant, request: Request, target: Target) -> str | None:
        return super().supports(hass, request, target) or unsupported_reason(target, self.scope.capabilities)

    async def execute(self, hass: HomeAssistant, request: Request, targets: list[Target]) -> list[EntityResult]:
        async def read(target: Target) -> EntityResult:
            status = await get_status(target)
            row = status_row(address(target).component, status, dt_util.utcnow())
            return self.result(target, Status.CONFIRMED, data=row)

        return await self.gather(hass, targets, read)
