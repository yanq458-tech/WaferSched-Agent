from copy import deepcopy
import json
from time import perf_counter

import pytest

from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.diagnose_hard import ROOT, load_case
from wafer_sched.recovery.healthy_witness import (
    find_healthy_schedule,
    lift_witness,
    verified_bypass,
)
from wafer_sched.recovery.incidents import scenarios
from wafer_sched.recovery.study_policy import adaptive


@pytest.mark.parametrize("n", [8, 12])
def test_constructive_schedule_certifies_without_accessing_failed_chamber(n):
    case = load_case(f"terminal-{n:02}-03")
    p, h = case.prepare()
    result, log = verified_bypass(case, p, h, perf_counter() + 10)
    assert result["status"] == "UNBOUNDED" and result["verification_valid"]
    assert set(result["completed_at"]) == set(p.snapshot["wafers"])
    assert result["makespan_optimal"] is False
    assert all(
        p.failed_chamber not in (t["source"], t["destination"])
        for t in result["best"]["schedule"]["transfers"]
    )
    assert log["proof"] == "complete_schedule_uses_no_failed_chamber"


def archived(n):
    case = load_case(f"terminal-{n:02}-03")
    data = json.loads(
        (ROOT / "stress30" / "runs" / f"terminal-{n:02}-03-0-graph_policy.json").read_text(
            encoding="utf8"
        )
    )
    return case, dict(verification_valid=data["raw_verified"], best=dict(schedule=data["schedule"]))


def test_legacy_tail_shift_preserves_pickup_and_is_parametrically_unbounded():
    case, result = archived(8)
    p, h = case.prepare()
    original = deepcopy(result)
    solved, proof = lift_witness(case, p, h, result)
    assert solved["status"] == "UNBOUNDED" and proof["wafer"] == "W7"
    assert proof["original_place_start"] / p.scale == 100.875
    assert result == original
    old = result["best"]["schedule"]["transfers"]
    new = solved["best"]["schedule"]["transfers"]
    assert old[:-2] == new[:-2] and old[-2]["pick_end"] == new[-2]["pick_end"]
    assert new[-2]["place_start"] > old[-2]["place_start"]


def test_finite_hold_or_another_unfinished_wafer_prevents_lifting():
    case, result = archived(8)
    raw = case.to_dict()
    raw["holding"]["W7"][1] = 1000
    case = Continuation.from_dict(raw)
    p, h = case.prepare()
    assert lift_witness(case, p, h, result) is None
    case, result = archived(12)
    p, h = case.prepare()
    assert lift_witness(case, p, h, result) is None


def test_failed_construction_does_not_prove_infeasibility():
    case = scenarios()["two"]
    p, _ = case.prepare()
    plan, meta = find_healthy_schedule(p, perf_counter() - 1)
    assert plan is None
    assert meta["outcome"] in ("probe_budget", "inapplicable")
    result = adaptive(case, 5, graph=True)
    assert result["status"] == "FINITE" and result["latest_repair_delay_seconds"] == 12
