import pytest

from custom_components.device_side.core.duration import clamp
from custom_components.device_side.core.models import TimedRequest
from custom_components.device_side.core.scope import DurationLimits

LIMITS = DurationLimits(min_s=1, max_s=100)


@pytest.mark.parametrize(
    ("requested", "sent", "clamped_to"),
    [
        (5, 5, None),
        (5.04, 5.04, None),  # in range: passed through unrounded
        (0.2, 1, 1),
        (500, 100, 100),
        (100.04, 100, 100),
    ],
)
def test_clamp(requested, sent, clamped_to):
    request, reported = clamp(TimedRequest(duration_s=requested), LIMITS)
    assert request.duration_s == sent
    assert reported == clamped_to


@pytest.mark.parametrize(
    ("limits", "requested", "sent", "clamped_to"),
    [
        (DurationLimits(min_s=0, max_s=100), 0.02, 0.05, 0.05),
        (DurationLimits(min_s=0, max_s=100), 0.05, 0.05, None),
        (None, 0.0, 0.05, 0.05),
        (None, 1000, 1000, None),
    ],
)
def test_floor_applies_and_is_reported_with_or_without_limits(limits, requested, sent, clamped_to):
    request, reported = clamp(TimedRequest(duration_s=requested), limits)
    assert request.duration_s == sent
    assert reported == clamped_to
