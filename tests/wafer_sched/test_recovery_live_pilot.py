from pathlib import Path
import json

import pytest

from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.feedback import live_pilot


class FakeClient:
    def __init__(self, tool):
        self.tool = tool

    def call(self, stage, context, schema, remaining):
        assert context["capacity_solver_feedback"]["upper_tick"] >= 0
        return {"tool": self.tool, "reason": "Test selected branch."}, {}


@pytest.mark.parametrize("tool", ["unlisted", "construct_at_upper", "cp_sat_at_upper"])
def test_planner_cannot_declare_or_remove_a_boundary(monkeypatch, tool):
    case = Continuation.from_dict(json.loads(Path(
        "results/recovery/feedback-study/holdout/inputs/new-16-m-f1.json"
    ).read_bytes()))
    calls = []
    def miss(*args):
        calls.append("construct_at_upper")
        return None, 1

    def timeout(*args):
        calls.append("cp_sat_at_upper")
        return "UNKNOWN", None, None, {"status": "UNKNOWN"}

    monkeypatch.setattr(live_pilot.grid, "construct", miss)
    monkeypatch.setattr(live_pilot.exact, "fixed_query", timeout)
    result = live_pilot.run(case, FakeClient(tool))
    assert calls == ([] if tool == "unlisted" else [tool])
    assert result["status"] == "UNKNOWN" and "schedule" not in result
    assert result["upper_seconds"] == (
        result["suffix_offset_seconds"] + result["capacity_feedback"]["upper_tick"] / result["scale"]
    )
