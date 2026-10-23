import pytest

from custom_components.device_side.core.capabilities import DurationLimits
from custom_components.device_side.core.duration import clamp
from custom_components.device_side.core.models import TimedRequest

LIMITS = DurationLimits(min_s=1, max_s=100, resolution_s=0.1)


@pytest.mark.parametrize(
    ("requested", "sent", "clamped_to"),
    [
        (5, 5, None),
        (5.04, 5.0, None),  # rounding to resolution is silent
        (0.2, 1, 1),
        (500, 100, 100),
        (100.04, 100, 100),
    ],
)
def test_clamp(requested, sent, clamped_to):
    request, reported = clamp(TimedRequest(duration_s=requested), LIMITS)
    assert request.duration_s == sent
    assert reported == clamped_to
