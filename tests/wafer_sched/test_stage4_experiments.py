"""Real decision differences, scale dimensions, and immutable historical data."""
from wafer_sched.infrastructure.provenance import assert_original_or_migrated

from dataclasses import asdict
import json

import pytest

from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.policies.rules import POLICIES, make_policy
from wafer_sched.policy_runner import run_policy
from wafer_sched import Simulator
from wafer_sched.stage4_scenarios import load_suite

NEW = [row for row in load_suite()["scenarios"] if row["group"] == "new_decision_cases"]


@pytest.mark.parametrize("row", NEW, ids=lambda row: row["scenario"])
@pytest.mark.parametrize("name", POLICIES)
def test_new_decision_cases_complete_through_original_simulator(row, name):
    sim = Simulator(row["equipment"])
    run = run_policy(sim, make_policy(name), max_time=row["window_seconds"])
    assert run.outcome["status"] == "completed"
    assert sim.validate_state()
    assert run.outcome["constraint_violations"] == 0


@pytest.mark.parametrize("row", NEW, ids=lambda row: row["scenario"])
def test_new_cases_have_multiple_feasible_action_sequences_not_just_different_labels(row):
    class ReverseLegal:
        name = "reverse_validation"

        def select_action(self, observation, legal_actions):
            work = [action for action in legal_actions if action.kind != "wait"]
            return work[-1] if work else legal_actions[0]

    first, second = Simulator(row["equipment"]), Simulator(row["equipment"])
    initial = [action for action in first.legal_actions() if action.kind != "wait"]
    assert len(initial) >= 2
    left = run_policy(first, make_policy("fifo"), max_time=row["window_seconds"])
    right = run_policy(second, ReverseLegal(), max_time=row["window_seconds"])
    assert left.outcome["status"] == right.outcome["status"] == "completed"
    left_sequence = [d["action"] for d in left.decisions if d["action"]["kind"] != "wait"]
    right_sequence = [d["action"] for d in right.decisions if d["action"]["kind"] != "wait"]
    assert left_sequence != right_sequence
    assert left_sequence[0] != asdict(initial[-1])


def test_scale_suite_increases_multiple_physical_dimensions():
    rows = [row for row in load_suite()["scenarios"] if row["group"] == "scale"]
    assert [len(row["equipment"].wafers) for row in rows] == [2, 8, 20]
    assert [len(row["equipment"].chambers) for row in rows] == [2, 4, 6]
    assert [len(row["equipment"].wafers[0].route) for row in rows] == [1, 3, 4]
    assert [row["size_class"] for row in rows] == ["small", "medium", "large"]


def test_stage3_historical_artifacts_and_core_semantics_are_preserved():
    path = PROJECT_ROOT / "docs/wafer_sched_stage4_preservation.json"
    hashes = json.loads(path.read_text(encoding="utf-8"))
    assert len(hashes) >= 400
    for relative, expected in hashes.items():
        assert_original_or_migrated(relative, expected)
