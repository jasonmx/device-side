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


def test_an_armed_value_is_echoed_once_within_the_tolerance(cache):
    cache.arm("light-1", {"brightness": 80.0, "on": True}, 5.0)

    assert cache.echoed("light-1", "brightness", 79.84)  # the bridge stores 80 % as 79.84
    assert not cache.echoed("light-1", "brightness", 79.84)
    assert not cache.echoed("light-1", "on", False)
    assert cache.echoed("light-1", "on", True)


@pytest.mark.parametrize(("value", "echoed"), [(80.5, True), (79.5, True), (80.6, False), (79.4, False)])
def test_echo_tolerance_edges(cache, value, echoed):
    cache.arm("light-1", {"brightness": 80.0}, 5.0)

    assert cache.echoed("light-1", "brightness", value) is echoed


def test_an_echo_expires_with_the_guard_window_and_disarm_drops_it(cache, clock):
    cache.arm("light-1", {"brightness": 80.0}, 5.0)
    cache.arm("light-2", {"brightness": 80.0}, 5.0)
    cache.disarm("light-2")
    clock.now += 5.0 + API_SETTLE_SECONDS + 0.1

    assert not cache.echoed("light-1", "brightness", 80.0)
    assert not cache.echoed("light-2", "brightness", 80.0)
    assert not cache.follows("light-1")


@pytest.mark.parametrize(
    ("value", "on_path"),
    [(19.5, True), (19.4, False), (35.18, True), (70.0, True), (80.5, True), (80.6, False)],
)
def test_on_path_spans_the_start_to_the_target_while_the_move_runs(cache, clock, value, on_path):
    cache.moving("light-1", "brightness", 20.0, 80.0, 10.0)
    clock.now += 5.0  # at 50 %

    assert cache.on_path("light-1", "brightness", value) is on_path


def test_on_path_moving_down_and_after_the_window(cache, clock):
    cache.moving("light-1", "brightness", 80.0, 20.0, 10.0)
    clock.now += 5.0

    assert cache.path("light-1", "brightness") == (20.0, 80.0)
    clock.now += 5.0 + API_SETTLE_SECONDS + 0.1
    assert not cache.on_path("light-1", "brightness", 20.0)


def test_follows_an_armed_echo_before_its_transition_is_recorded(cache):
    assert not cache.follows("light-1")
    cache.arm("light-1", {"brightness": 80.0}, 5.0)

    assert cache.follows("light-1")
    cache.echoed("light-1", "brightness", 80.0)
    assert not cache.follows("light-1")


def test_forget_drops_the_resources_transitions_and_echo(cache):
    cache.moving("light-1", "brightness", 20.0, 80.0, 10.0)
    cache.moving("light-1", "color_temp", 200.0, 300.0, 10.0)
    cache.arm("light-1", {"brightness": 80.0}, 10.0)
    cache.stopped("light-2", "brightness", 42.0)

    cache.forget("light-1")

    assert not cache.follows("light-1")
    assert cache.value("light-1", "brightness", 13.0) == 13.0
    assert cache.value("light-2", "brightness", 13.0) == 42.0
