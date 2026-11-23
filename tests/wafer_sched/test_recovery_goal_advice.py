import json
from concurrent.futures import Future
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import pytest

from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.feedback import policy
from wafer_sched.recovery.feedback.goal_advice import GoalAdvisor, parse_goal


class SynchronousExecutor:
    def submit(self, fn):
        f = Future()
        f.set_result(fn())
        return f


@pytest.mark.parametrize("goal", ["find_witness", "tighten_upper", "keep_local", "unlisted"])
def test_objectives_consume_completed_feedback_and_do_not_create_proofs(monkeypatch, goal):
    incident = Continuation.from_dict(json.loads(Path(
        "results/recovery/feedback-study/final-holdout/inputs/blind-16-h-f1.json"
    ).read_bytes()))
    prompts, queries = [], []

    def call(stage, context, schema, left):
        prompts.append(context)
        assert stage == "recovery_after_fixed_query"
        assert context["recent"][-1]["status"] == "UNKNOWN" and not context["has_verified_schedule"]
        return {"goal": goal, "reason": "No completed schedule has been verified."}, {}

    advisor = GoalAdvisor(SimpleNamespace(call=call), SynchronousExecutor())
    monkeypatch.setattr(policy.terminal_exact, "solve_terminal", lambda *args: dict(status="UNKNOWN", trace=[]))
    monkeypatch.setattr(policy.grid, "construct", lambda *args: (None, 1))
    monkeypatch.setattr(policy.capacity, "bound", lambda p, d, hi, t: (
        hi, dict(tool="prefix_capacity_relaxation", status="FEASIBLE", upper_tick=hi)))
    def fixed(p, d, q, deadline, *, seed=0):
        queries.append((q,seed))
        return "UNKNOWN", None, None, {"status":"UNKNOWN"}
    monkeypatch.setattr(policy.exact, "fixed_query", fixed)
    result = policy.solve(incident, 6, "plain", goal_advisor=advisor)
    assert len(prompts) == 1 and result["status"] == "UNKNOWN"
    assert not result.get("verification_valid")
    actions = [t for t in result["trace"] if t["tool"] == "execute_advised_goal"]
    if goal == "find_witness":
        assert queries[:2] == [(0,0),(0,1)] and actions[0]["goal"] == goal
    elif goal == "tighten_upper":
        assert queries[1][0] == prompts[0]["upper_tick"] and actions[0]["goal"] == goal
    else:
        assert not actions
        assert advisor.event["outcome"] == ("kept_local" if goal == "keep_local" else "invalid_or_unavailable")


def test_long_explanation_preserves_allowlisted_decision():
    parsed = parse_goal({"goal":"keep_local", "reason":"a"*186})
    assert parsed.goal == "keep_local" and len(parsed.reason) == 180


def test_pending_or_expired_goal_never_blocks_or_changes_local_actions():
    planner = GoalAdvisor(None, None)
    planner.future = Future()
    planner.event = {"outcome":"unused_at_stop"}
    assert planner.take(perf_counter()+5) is None
    planner.future.set_result(({"goal":"tighten_upper","reason":"Upper remains open"}, {}))
    assert planner.take(perf_counter()-1) is None
    assert planner.event["outcome"] == "unused_at_stop"
