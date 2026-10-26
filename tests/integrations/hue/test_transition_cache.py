"""TransitionCache: the predicted value inside the guard window, the reported one after; ported from hue_dimmer."""

import pytest

from custom_components.device_side.integrations.hue.transition_cache import API_SETTLE_SECONDS, TransitionCache

from .conftest import Clock


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def cache(clock) -> TransitionCache:
    return TransitionCache(clock)


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
    clock.now += duration + API_SETTLE_SECONDS + 0.1

    assert cache.value("light-1", "brightness", 70.0) == 70.0
    clock.now = 1000.0
    assert cache.value("light-1", "brightness", 70.0) == 70.0


def test_keys_are_per_resource_and_attribute(cache):
    cache.stopped("light-1", "brightness", 42.0)

    assert cache.value("light-2", "brightness", 10.0) == 10.0
    assert cache.value("light-1", "color_temp", 10.0) == 10.0
