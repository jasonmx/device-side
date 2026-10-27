from datetime import UTC, datetime

from homeassistant.util import dt as dt_util

from custom_components.device_side.core.timer import timer_row

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_timer_row_ends_after_the_remaining_time():
    assert timer_row("off", 90.04, NOW) == {
        "turns": "off",
        "ends_at": "2026-10-27T12:01:30+00:00",
        "remaining_s": 90.0,
    }


def test_timer_row_defaults_to_now(monkeypatch):
    monkeypatch.setattr(dt_util, "utcnow", lambda: NOW)
    assert timer_row("on", 0.5)["ends_at"] == "2026-10-27T12:00:00.500000+00:00"
