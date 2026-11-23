from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from time import perf_counter
from types import SimpleNamespace

import pytest

from wafer_sched.recovery.feedback.async_advice import StallAdvisor


def test_advice_is_nonblocking_and_never_applies_a_stale_tick():
    entered, release = Event(), Event()

    def slow_request(stage, context, schema, remaining):
        assert stage == "recovery_after_local_stall"
        assert context["options"] == {"upper": 10, "middle": 5}
        entered.set()
        assert release.wait(5)
        return {"target": "upper", "tool": "exact"}, {}

    with ThreadPoolExecutor(max_workers=1) as pool:
        planner = StallAdvisor(SimpleNamespace(call=slow_request), pool)
        end = perf_counter() + 20
        planner.on_stall(-1, 10, {0}, 0, 16, 8, 2, end)
        try:
            assert entered.wait(2)
            start = perf_counter()
            assert planner.poll(-1, 10, {0}, end) is None
            planner.record_local(start, perf_counter(), 0)
        finally:
            release.set()
        planner.future.result(timeout=2)
        assert planner.poll(-1, 9, {0}, end) is None
        assert planner.event["outcome"] == "stale"
        assert planner.accounting()["local_exact_overlap_seconds"] > 0


@pytest.mark.parametrize(("target", "outcome"), [("middle", "applied"), ("zero", "invalid_or_unavailable")])
def test_advice_is_one_shot_and_only_chooses_an_offered_query(target, outcome):
    def submit(task):
        f = Future()
        f.set_result(task())
        return f

    planner = StallAdvisor(SimpleNamespace(call=lambda *args: ({"target": target, "tool": "exact"}, {})),
                           SimpleNamespace(submit=submit))
    end = perf_counter() + 20
    planner.on_stall(-1, 10, {0}, 0, 16, 8, 0, end)
    assert planner.future is None  # No local attempts.
    planner.on_stall(-1, 10, {0}, 0, 16, 8, 2, perf_counter() + 1)
    assert planner.future is None  # Insufficient remaining time.
    planner.on_stall(-1, 10, {0}, 0, 16, 8, 2, end)
    f = planner.future
    planner.on_stall(-1, 10, {0}, 0, 16, 8, 2, end)
    assert planner.future is f
    assert planner.poll(-1, 10, {0}, perf_counter() - 1) is None
    chosen = planner.poll(-1, 10, {0}, end)
    assert (chosen[0] if chosen else None) == (5 if target == "middle" else None)
    assert planner.event["outcome"] == outcome
    assert planner.poll(-1, 10, {0}, end) is None
