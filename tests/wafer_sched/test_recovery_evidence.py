from copy import deepcopy
import json
from pathlib import Path

import pytest

from wafer_sched.recovery.conflict_evidence import best_bound, verify_bound
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.direct import direct
from wafer_sched.recovery.incidents import scenarios
from wafer_sched.recovery.milp_reference import reference_incident
from wafer_sched.recovery.study_policy import adaptive


@pytest.fixture(scope="module")
def cases():
    cases = scenarios()
    path = Path(__file__).resolve().parents[2] / "data/recovery-study/fractional-seed.json"
    cases["fractional"] = Continuation.from_dict(json.loads(path.read_text()))
    return cases


@pytest.mark.parametrize(
    "name,status,rho",
    [
        ("two", "FINITE", 12),
        ("mid_pick", "FINITE", 11.5),
        ("fractional", "FINITE", 9.25),
        ("evacuate", "UNBOUNDED", None),
        ("overload", "INFEASIBLE_AT_ZERO", None),
        ("interrupted_process", "UNSUPPORTED", None),
    ],
)
def test_direct(cases, name, status, rho):
    result = direct(cases[name])
    assert result["status"] == status
    assert result.get("latest_repair_delay_seconds") == rho
    if rho is not None:
        assert result["verification_valid"] and result["makespan_optimal"]
        assert set(result["completed_at"]) == set(cases[name].residency)


@pytest.mark.parametrize(
    "r,status,makespan", [(9.25, "OPTIMAL", 20.75), (9.3125, "INFEASIBLE", None)]
)
def test_independent_milp_fractional(cases, r, status, makespan):
    result = reference_incident(cases["fractional"], r)
    assert (result["status"], result.get("makespan_seconds")) == (status, makespan)


def test_zero_budget_and_assignment_limit(cases):
    assert direct(cases["fractional"], 0)["status"] == "UNKNOWN"
    assert reference_incident(cases["two"], 0, assignment_limit=1)["status"] == "SIZE_LIMIT"
    assert reference_incident(cases["two"], 0, seconds=0)["status"] == "UNKNOWN"


def test_certificate_rejects_missing_route_and_forged_upper(cases):
    p, prefix = cases["fractional"].prepare()
    cert = best_bound(p)
    assert verify_bound(p, cert)
    assert prefix["offset"] + cert["upper_tick"] / p.scale == 9.25
    missing = deepcopy(cert)
    missing["branches"].pop()
    assert not verify_bound(p, missing)
    forged = deepcopy(cert)
    forged["upper_tick"] -= 1
    assert not verify_bound(p, forged)


def test_sealed_policy_essential(cases):
    sealed, _ = cases["sealed"].prepare()
    open_case, _ = cases["evacuate"].prepare()
    cert = best_bound(sealed)
    assert verify_bound(sealed, cert) and not verify_bound(open_case, cert)


@pytest.mark.parametrize("graph", [False, True])
def test_policy_feedback_and_replayed_hint(cases, graph):
    result = adaptive(cases["two"], 3, graph=graph)
    assert result["latest_repair_delay_seconds"] == 12 and result["verification_valid"]
    first, second = [t for t in result["policy_trace"] if t["tool"] != "healthy_completion"]
    assert first["delay"] == 0 and second["verified_hint"]


def test_mandatory_load_certificate_requires_exactly_one_destination():
    from wafer_sched.recovery.study_data import terminal_case
    from wafer_sched.recovery.conflict_evidence import deadline_bounds

    case = terminal_case(4, 2)
    p, _ = case.prepare()
    cert = next(c for c in deadline_bounds(p) if c["kind"] == "mandatory_load")
    assert verify_bound(p, cert)
    corrupt = {**cert, "holding_tick": cert["holding_tick"] + 1}
    assert not verify_bound(p, corrupt)
    raw = case.to_dict()
    raw["config"]["wafers"][0]["route"][-1]["chambers"].append("H1")
    alternative, _ = Continuation.from_dict(raw).prepare()
    assert not verify_bound(alternative, cert)


def test_exact_zero_is_distinct_from_unrecoverable(cases):
    raw = cases["sealed"].to_dict()
    raw["residency"]["W2"][0] -= 3
    result = direct(Continuation.from_dict(raw))
    assert result["status"] == "FINITE" and result["latest_repair_delay_seconds"] == 0
    assert result["verification_valid"]
