"""DeviceSideData.schedule and cancel_pending: delayed jobs keyed by the caller."""

from unittest.mock import MagicMock

from custom_components.device_side.core.runtime import DeviceSideData

from ..conftest import advance, wall_clock_now


def _runtime() -> DeviceSideData:
    return DeviceSideData(registry=MagicMock(), dispatcher=MagicMock())


def _recorder(ran: list[str], name: str):
    async def job() -> None:
        ran.append(name)

    return job


async def test_jobs_run_after_their_delays_and_leave_nothing_pending(hass):
    runtime, ran, start = _runtime(), [], wall_clock_now()

    runtime.schedule(hass, "k", [(1, _recorder(ran, "a")), (5, _recorder(ran, "b"))])
    assert len(runtime.pending["k"]) == 2

    await advance(hass, start, 1.5)
    assert ran == ["a"]
    assert len(runtime.pending["k"]) == 1
    await advance(hass, start, 5.5)
    assert ran == ["a", "b"]
    assert runtime.pending == {}


async def test_rescheduling_a_key_cancels_its_pending_jobs_only(hass):
    runtime, ran, start = _runtime(), [], wall_clock_now()

    runtime.schedule(hass, "k", [(1, _recorder(ran, "old"))])
    runtime.schedule(hass, "other", [(1, _recorder(ran, "other"))])
    runtime.schedule(hass, "k", [(2, _recorder(ran, "new"))])

    await advance(hass, start, 2.5)
    assert sorted(ran) == ["new", "other"]


async def test_no_jobs_leaves_nothing_pending(hass):
    runtime = _runtime()

    runtime.schedule(hass, "k", [])

    assert runtime.pending == {}


async def test_cancel_pending_cancels_every_key(hass):
    runtime, ran, start = _runtime(), [], wall_clock_now()
    runtime.schedule(hass, "a", [(1, _recorder(ran, "a"))])
    runtime.schedule(hass, "b", [(1, _recorder(ran, "b"))])

    runtime.cancel_pending()
    await advance(hass, start, 2)

    assert ran == []
    assert runtime.pending == {}
