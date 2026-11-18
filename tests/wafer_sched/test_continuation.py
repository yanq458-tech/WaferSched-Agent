"""Fault-clock regressions and independent primitive-path checks for v1.3."""

import json
from dataclasses import replace

import pytest

from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.dispatch import recover
from wafer_sched.recovery.incidents import scenarios
from wafer_sched.recovery.primitive_oracle import enumerate_incident


@pytest.fixture(scope="module")
def cases():
    return scenarios()


@pytest.mark.parametrize(
    "name,phase", [("mid_pick", "picking"), ("mid_place", "placing"), ("mid_move", "moving_loaded")]
)
def test_irrevocable_prefix_roundtrip(cases, name, phase):
    original = cases[name]
    case = Continuation.from_dict(json.loads(json.dumps(original.to_dict())))
    assert case.to_dict() == original.to_dict()
    result = recover(case, "solve", repair=5)
    prefix = result["prefix"]
    assert prefix["committed_robot"]["phase"] == phase
    assert prefix["dispatch_time"] == case.snapshot["robot"]["phase_end"]
    assert prefix["events"] and result["verification_valid"]
    assert set(result["completed_at"]) == set(case.residency)
    oracle = enumerate_incident(case, 5)
    assert oracle["status"] == result["status"] == "OPTIMAL"
    assert oracle["makespan_seconds"] == result["makespan_seconds"]


def test_snapshot_requires_consistent_physical_history(cases):
    raw = cases["mid_place"].to_dict()
    raw["snapshot"]["robot"]["phase_end"] += 1
    with pytest.raises(ValueError, match="disagrees"):
        Continuation.from_dict(raw).prepare()


@pytest.mark.parametrize("name", ["unqualified", "fault_during_load", "interrupted_process"])
def test_out_of_scope_is_not_infeasible(cases, name):
    assert recover(cases[name])["status"] == "UNSUPPORTED"


def test_occupied_fault_policy_changes_exact_boundary(cases):
    assert recover(cases["evacuate"], "boundary")["status"] == "UNBOUNDED"
    result = recover(cases["sealed"], "boundary")
    assert result["status"] == "FINITE"
    rho = result["latest_repair_delay_seconds"]
    assert enumerate_incident(cases["sealed"], rho)["status"] == "OPTIMAL"
    assert enumerate_incident(cases["sealed"], rho + 1)["status"] == "INFEASIBLE"


def test_irrevocable_pick_misses_residency(cases):
    case = cases["mid_pick"]
    r = {**case.residency, "W2": [0, 1]}
    result = recover(replace(case, residency=r), "solve")
    assert result["status"] == "INFEASIBLE"
    assert result["proof_source"] == "committed_quality_violation"


def test_elapsed_dispatch_clock_and_repair_before_release(cases):
    case = replace(cases["mid_pick"], dispatch_lag=2)
    for repair in (0, 1, 2):
        result = recover(case, "solve", repair=repair)
        oracle = enumerate_incident(case, repair)
        assert result["status"] == oracle["status"]
        assert result.get("makespan_seconds") == oracle.get("makespan_seconds")
    assert recover(replace(case, dispatch_lag=20), "boundary")["status"] == "INFEASIBLE_AT_ZERO"


def test_fractional_boundary_and_verified_hint(cases):
    result = recover(cases["mid_pick"], "boundary")
    assert result["latest_repair_delay_seconds"] == 11.5
    assert result["optimization"]["verified_time_hint"]
    assert result["makespan_optimal"]
    assert recover(cases["mid_pick"], "solve", repair=11.75)["status"] == "INFEASIBLE"


def test_resource_certificate_and_identical_baseline(cases):
    case = cases["overload"]
    fast = recover(case, "solve")
    assert fast["best"]["proof_source"] == "initial_pickup_workload"
    assert fast["status"] == recover(case, "solve", optimized=False)["status"] == "INFEASIBLE"


def test_budget_retains_witness_and_reports_unknown(cases):
    result = recover(cases["mid_pick"], max_rounds=1)
    assert result["status"] == "UNKNOWN" and result["verification_valid"]
    assert recover(cases["mid_pick"], total=0)["status"] == "UNKNOWN"
    assert enumerate_incident(cases["two"], 0, max_states=1)["status"] == "UNKNOWN"


def test_clock_check_rejects_missed_first_command(cases):
    from wafer_sched.recovery.dispatch import dispatch_window

    result = recover(cases["mid_pick"], "solve")
    first = dispatch_window(result, 0)["first_command_delay_seconds"]
    assert dispatch_window(result, first)["status"] == "ON_TIME"
    assert dispatch_window(result, first + 0.1)["status"] == "STALE_PLAN"


def test_carried_wafer_holding_deadline_across_place_commit(cases):
    case = cases["mid_place"]
    result = recover(replace(case, holding={**case.holding, "W2": [None, 0, None]}), "solve")
    assert result["proof_source"] == "committed_quality_violation"


def test_interrupted_empty_move_and_final_committed_unload():
    from wafer_sched import Simulator
    from wafer_sched.actions import Action
    from wafer_sched.config import EquipmentConfig

    cfg = EquipmentConfig.from_dict(
        {
            "robot": {"pick_seconds": 1, "place_seconds": 1, "move_seconds": 2},
            "chambers": [{"id": c, "processing_times": {"p": 1}} for c in ["S", "F"]],
            "wafers": [{"id": "W", "route": [{"recipe": "p", "chambers": ["S"]}]}],
        }
    )
    sim = Simulator(cfg)
    assert sim.submit(Action.transfer("W", "S"))
    while sim.state.robot.busy:
        sim.advance_next()
    assert sim.submit(Action.move("F"))
    sim.run_until(sim.state.time + 1)
    case = Continuation.capture(sim, "F", {"W": [20]})
    assert case.snapshot["robot"]["phase"] == "moving_empty"
    assert recover(case, "solve")["verification_valid"]
    sim.advance_next()
    for action in [Action.move("S"), Action.pick("W", "S"), Action.move("OUT")]:
        assert sim.submit(action)
        while sim.state.robot.busy:
            sim.advance_next()
    assert sim.submit(Action.place("W", "OUT"))
    sim.run_until(sim.state.time + 0.5)
    case = Continuation.capture(sim, "F", {"W": [20]}, dispatch_lag=3)
    result = recover(case)
    assert result["status"] == "UNBOUNDED" and result["makespan_seconds"] == 0.5
    assert enumerate_incident(case, 10)["makespan_seconds"] == 0.5
