"""The `timer` entry of a get_attributes row, shared so every integration reports an on/off timer alike."""

from datetime import datetime, timedelta
from typing import Literal

from homeassistant.util import dt as dt_util


def timer_row(turns: Literal["on", "off"], remaining_s: float, now: datetime | None = None) -> dict:
    """A running timer, from the time the device reports left on it: what it turns the target to, and when.

    ends_at is UTC ISO 8601, so a template can compare it with now(). Call only while a timer runs: with none,
    the row has no `timer` key, rather than a zero one.
    """
    remaining_s = round(remaining_s, 1)
    ends_at = (now or dt_util.utcnow()) + timedelta(seconds=remaining_s)
    return {"turns": turns, "ends_at": ends_at.isoformat(), "remaining_s": remaining_s}
