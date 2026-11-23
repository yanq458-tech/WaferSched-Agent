from concurrent.futures import Future
from types import SimpleNamespace
from time import perf_counter

import pytest

from wafer_sched.recovery.feedback.live_comparison import TimedChoice


@pytest.mark.parametrize(("response", "seconds", "outcome"), [
    ({"target": "upper", "tool": "exact"}, 2, "applied"),
    ({"target": "zero", "tool": "exact"}, 2, "invalid_or_unavailable"),
    ({"target": "upper", "tool": "exact"}, -1, "expired"),
    (None, 0.001, "expired"),
])
def test_only_valid_on_time_queries_can_reach_solver(response, seconds, outcome):
    future = Future()
    if response is not None:
        future.set_result((response, {}))
    planner = TimedChoice(SimpleNamespace(call=None), SimpleNamespace(submit=lambda *args: future))
    decision, event = planner({"options": {"upper": 1}}, perf_counter() + seconds)
    assert event["outcome"] == outcome
    assert (decision is not None) == (outcome == "applied")
    assert event["waited_seconds"] >= 0
