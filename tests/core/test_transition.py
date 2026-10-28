"""TransitionCache: the predicted value inside the guard window, the reported one after; ported from hue_dimmer."""

import pytest

from custom_components.device_side.core.transition import TransitionCache, transition_cache

SETTLE_SECONDS = 15.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def cache(clock) -> TransitionCache:
    return TransitionCache(SETTLE_SECONDS, clock)


def test_nothing_cached_returns_the_reported_value(cache):
    assert cache.value("light-1", "brightness", 60.0) == 60.0


@pytest.mark.parametrize(
    ("start", "target", "duration", "elapsed", "expected"),
    [
        pytest.param(30.0, 100.0, 7.0, 5.0, 80.0, id="moving_up_interpolates"),
        pytest.param(70.0, 20.0, 5.0, 2.5, 45.0, id="moving_down_interpolates"),
        pytest.param(90.0, 100.0, 0.5, 10.0, 100.0, id="holds_the_target_once_reached"),
        pytest.param(42.0, 42.0, 0.0, 5.0, 42.0, id="stopped_holds_its_value"),
    ],
)
def test_inside_the_guard_the_prediction_wins(cache, clock, start, target, duration, elapsed, expected):
    cache.moving("light-1", "brightness", start, target, duration)
    clock.now += elapsed

    assert cache.value("light-1", "brightness", 13.0) == pytest.approx(expected)


@pytest.mark.parametrize("duration", [pytest.param(5.0, id="moving"), pytest.param(0.0, id="stopped")])
def test_after_the_guard_the_report_wins_and_the_entry_is_pruned(cache, clock, duration):
    cache.moving("light-1", "brightness", 30.0, 100.0, duration)
    clock.now += duration + SETTLE_SECONDS + 0.1

    assert cache.value("light-1", "brightness", 70.0) == 70.0
    clock.now = 1000.0
    assert cache.value("light-1", "brightness", 70.0) == 70.0


def test_keys_are_per_resource_and_attribute(cache):
    cache.stopped("light-1", "brightness", 42.0)

    assert cache.value("light-2", "brightness", 10.0) == 10.0
    assert cache.value("light-1", "color_temp", 10.0) == 10.0


def test_follows_any_attribute_inside_its_window(cache, clock):
    assert not cache.follows("light-1")
    cache.moving("light-1", "brightness", 20.0, 80.0, 10.0)
    cache.stopped("light-1", "color_temp", 300.0)

    assert cache.attributes("light-1") == ["brightness", "color_temp"]
    clock.now += SETTLE_SECONDS + 0.1
    assert cache.attributes("light-1") == ["brightness"]
    clock.now += 10.0
    assert not cache.follows("light-1")


def test_forget_drops_the_resources_transitions_and_restore_puts_them_back(cache):
    cache.moving("light-1", "brightness", 20.0, 80.0, 10.0)
    cache.moving("light-1", "color_temp", 200.0, 300.0, 10.0)
    cache.stopped("light-2", "brightness", 42.0)

    forgotten = cache.forget("light-1")

    assert not cache.follows("light-1")
    assert cache.value("light-1", "brightness", 13.0) == 13.0
    assert cache.value("light-2", "brightness", 13.0) == 42.0
    cache.restore(forgotten)
    assert cache.attributes("light-1") == ["brightness", "color_temp"]


async def test_recording_keeps_what_an_accepted_write_records(cache):
    async with cache.recording([("light-1", "brightness")]):
        cache.stopped("light-1", "brightness", 42.0)

    assert cache.value("light-1", "brightness", 13.0) == 42.0


async def test_a_refused_write_puts_back_what_each_key_held(cache):
    cache.stopped("light-1", "brightness", 42.0)

    with pytest.raises(RuntimeError):
        async with cache.recording([("light-1", "brightness"), ("light-2", "brightness")]):
            cache.moving("light-1", "brightness", 42.0, 100.0, 5.0)
            cache.moving("light-2", "brightness", 0.0, 100.0, 5.0)
            raise RuntimeError("refused")

    assert cache.halted("light-1", "brightness")
    assert cache.value("light-1", "brightness", 13.0) == 42.0
    assert not cache.follows("light-2")


async def test_each_integration_keeps_its_own_cache(hass, setup_integration):
    hue = transition_cache(hass, "hue", lambda: TransitionCache(15))
    z2m = transition_cache(hass, "zigbee2mqtt", lambda: TransitionCache(1))

    assert transition_cache(hass, "hue", lambda: TransitionCache(0)) is hue
    assert z2m is not hue
    assert (hue.settle_seconds, z2m.settle_seconds) == (15, 1)
