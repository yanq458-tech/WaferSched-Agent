"""Independent enumeration, real-engine replay, status and boundary regressions."""

from copy import deepcopy
from dataclasses import replace

import pytest

from wafer_sched.actions import Action
from wafer_sched.config import EquipmentConfig
from wafer_sched.cpsat_model import UnsupportedModel
from wafer_sched.cpsat_solver import SolverOptions
from wafer_sched.recovery import RecoveryProblem, repair_boundary, solve_recovery
from wafer_sched.recovery.bounds import joint_bound, symmetric_formula
from wafer_sched.recovery.enumeration import enumerate_terminal
from wafer_sched.recovery.examples import terminal_competition
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.simulator import Simulator


OPTIONS = SolverOptions(max_seconds=3, log_search=False)


@pytest.mark.parametrize("m,D,p,delta", [(1,3,3,1), (1,4,5,2), (2,5,5,1), (2,6,10,1)])
def test_symmetric_boundary_against_independent_enumeration(m, D, p, delta):
    problem = terminal_competition(m=m, deadline=D, processing=p, residency=delta)
    expected = D+p+delta-2*m-1
    assert symmetric_formula(problem) == expected
    boundary = repair_boundary(problem, OPTIONS, use_joint_bound=True)
    assert boundary["status"] == "FINITE"
    assert boundary["latest_repair_delay_seconds"] == expected
    for r, feasible in ((expected, True), (expected+1, False)):
        oracle = enumerate_terminal(problem, r)
        exact = solve_recovery(problem, r, OPTIONS)
        assert exact.feasible == feasible
        assert oracle["status"] == ("FEASIBLE" if feasible else "INFEASIBLE")
        if feasible:
            assert exact.metadata["makespan_seconds"] == oracle["makespan_seconds"]
            assert exact.replay["valid"]


@pytest.mark.parametrize("ps,ds,rs", [([6,8],[4,5],[1,2]), ([7,6,9],[5,6,7],[2,1,3]),
                                      ([6,9,7],[6,6,6],[1,3,2])])
def test_heterogeneous_pruning_preserves_exhaustive_feasibility(ps, ds, rs):
    problem = terminal_competition(m=len(ps)-1, process_times=ps, deadlines=ds, residencies=rs)
    assert symmetric_formula(problem) is None
    cap = joint_bound(problem)
    for r in range(0, 15):
        oracle = enumerate_terminal(problem, r)
        assert oracle["status"] != "UNKNOWN"
        a = solve_recovery(problem, r, OPTIONS)
        b = solve_recovery(problem, r, OPTIONS, use_joint_bound=True)
        assert a.feasible == b.feasible == (oracle["status"] == "FEASIBLE")
        if cap and r > cap["upper_tick"]:
            assert not a.feasible


def test_capacity_bound():
    p = terminal_competition(m=1, count=3, deadline=6, processing=6)
    assert joint_bound(p)["kind"] == "evacuation_capacity"
    assert solve_recovery(p, 7, OPTIONS).metadata["status"] == "INFEASIBLE"


def test_unbounded_even_when_failed_chamber_is_mandatory():
    p = terminal_competition(m=0, count=1, deadline=2, processing=3)
    r = repair_boundary(p, OPTIONS)
    assert r["status"] == "UNBOUNDED"
    assert r["best"]["verification"]["valid"]
    assert any(t["destination"] == "F" for t in r["best"]["schedule"]["transfers"])


def test_unbounded_by_bypassing_fault():
    p = terminal_competition(m=1, count=1, deadline=2, processing=3)
    assert repair_boundary(p, OPTIONS)["status"] == "UNBOUNDED"


def test_immediate_infeasibility_is_not_zero_boundary():
    p = terminal_competition(m=1, deadline=0, processing=3)
    r = repair_boundary(p, OPTIONS)
    assert r["status"] == "INFEASIBLE_AT_ZERO"
    assert r["latest_repair_delay_seconds"] is None


def test_zero_is_a_real_attained_finite_boundary():
    p = terminal_competition(m=0, count=1, deadline=2, processing=3)
    # Carrying at the fault instant with exactly one place-duration left.
    sim = p.simulator(0)
    assert sim.submit(Action.move("S1"))
    assert sim.submit(Action.pick("W1", "S1"))
    while sim.state.robot.busy:
        sim.advance_next()
    snap = sim.snapshot()
    snap["carrying_since"] = sim.state.time
    holding = {"W1": [None, 1, None]}
    q = RecoveryProblem(p.config, snap, "F", p.residency, holding)
    result = repair_boundary(q, OPTIONS)
    assert result["status"] == "FINITE"
    assert result["latest_repair_delay_seconds"] == 0
    assert result["best"]["verification"]["valid"]


def test_initial_active_process_uses_remaining_time_not_full_duration():
    p = terminal_competition(m=1, deadline=4, processing=5)
    sim = Simulator(p.config)
    for i in (1, 2):
        assert sim.submit(Action.transfer(f"W{i}", f"S{i}"))
        while sim.state.robot.busy:
            sim.advance_next()
    assert sim.state.time == 4
    assert all(sim.state.chambers[f"S{i}"].remaining == 1 for i in (1, 2))
    q = RecoveryProblem(p.config, sim.snapshot(), "F", p.residency)
    a = solve_recovery(q, 0, OPTIONS)
    assert a.feasible
    assert min(t["pick_start"] for t in a.schedule["transfers"]) >= 1
    assert a.replay["valid"]


def test_unknown_and_exhausted_budget_do_not_claim_infeasibility():
    p = terminal_competition()
    r = solve_recovery(p, 0, replace(OPTIONS, max_seconds=0))
    assert r.metadata["status"] == "UNKNOWN"
    b = repair_boundary(p, replace(OPTIONS, max_seconds=0))
    assert b["status"] == "UNKNOWN"
    assert b["proven_infeasible_upper_seconds"] is None
    assert repair_boundary(p, OPTIONS, total_seconds=0)["status"] == "UNKNOWN"


def test_unknown_after_a_feasible_query_preserves_witness_and_bounds(monkeypatch):
    import wafer_sched.recovery.boundary as module
    p = terminal_competition()
    real = module.solve_recovery
    def limited(problem, r, options, **kw):
        return real(problem, r, replace(options, max_seconds=0) if r else options, **kw)
    monkeypatch.setattr(module, "solve_recovery", limited)
    b = repair_boundary(p, OPTIONS)
    assert b["status"] == "UNKNOWN"
    assert b["verified_feasible_lower_seconds"] == 0
    assert b["proven_infeasible_upper_seconds"] is None
    assert b["best"]["verification"]["valid"]


def test_fractional_times_no_rounding_and_continuous_boundary():
    p = terminal_competition(m=1, deadline=5.5, processing=6.25, residency=1.25)
    assert p.scale == 4
    b = repair_boundary(p, OPTIONS)
    assert b["status"] == "FINITE" and b["latest_repair_delay_seconds"] == 10
    assert solve_recovery(p, 10.25, OPTIONS).metadata["status"] == "INFEASIBLE"
    with pytest.raises(UnsupportedModel):
        solve_recovery(p, 10.1, OPTIONS)


def test_independent_validator_rejects_tampered_residency_even_if_engine_allows_it():
    p = terminal_competition(m=0, count=1, deadline=2, processing=3, residency=1)
    r = solve_recovery(p, 0, OPTIONS)
    schedule = deepcopy(r.schedule)
    last = schedule["transfers"][-1]
    for key in ("pick_start", "pick_end", "place_start", "place_end"):
        last[key] += 1
    schedule["makespan_tick"] += 1
    report = replay_recovery(p, 0, schedule)
    assert not report["valid"]
    assert any("residency" in error for error in report["errors"])


def test_replay_and_solve_leave_input_untouched_and_roundtrip():
    p = terminal_competition()
    before = deepcopy(p.to_dict())
    q = RecoveryProblem.from_dict(before)
    assert solve_recovery(q, 12, OPTIONS).feasible
    assert p.to_dict() == before == q.to_dict()


def test_busy_robot_and_occupied_failed_chamber_are_rejected_explicitly():
    p = terminal_competition()
    with pytest.raises(UnsupportedModel, match="empty"):
        RecoveryProblem(p.config, p.snapshot, "S1", p.residency)
    sim = p.simulator(0)
    assert sim.submit(Action.move("S1"))
    assert sim.submit(Action.pick("W1", "S1"))
    with pytest.raises(UnsupportedModel, match="boundary"):
        RecoveryProblem(p.config, sim.snapshot(), "F", p.residency)


def test_unmodelled_actions_and_nonmetric_travel_are_not_silently_removed():
    p = terminal_competition()
    with pytest.raises(UnsupportedModel, match="action set"):
        RecoveryProblem(p.config, p.snapshot, "F", p.residency, allowed_actions=("transfer",))
    data = p.config.to_dict()
    data["robot"]["travel_times"] = [{"source": "S1", "destination": "H1", "seconds": 1}]
    with pytest.raises(UnsupportedModel, match="triangle"):
        RecoveryProblem(EquipmentConfig.from_dict(data), p.snapshot, "F", p.residency)


def test_directed_metric_travel_and_remaining_multiple_operations():
    cfg = EquipmentConfig.from_dict({"robot": {"pick_seconds": .5, "place_seconds": .5,
        "move_seconds": 1, "travel_times": [{"source": "A", "destination": "B", "seconds": 2}]},
        "chambers": [{"id": "A", "processing_times": {"x": 2}},
                     {"id": "B", "processing_times": {"y": 3}},
                     {"id": "F", "processing_times": {"y": 4}}],
        "wafers": [{"id": "W", "route": [{"recipe": "x", "chambers": ["A"]},
                    {"recipe": "y", "chambers": ["B", "F"]},
                    {"recipe": "x", "chambers": ["A"]}]}]})
    sim = Simulator(cfg)
    p = RecoveryProblem(cfg, sim.snapshot(), "F", {"W": [1, 1, 1]})
    a = solve_recovery(p, 100, OPTIONS)
    assert a.feasible and a.replay["valid"]
    assert len(a.schedule["processes"]) == 3


@pytest.mark.parametrize("kind", ["finite", "heterogeneous", "unbounded"])
def test_offline_agent_executes_feedback_changes_for_three_classes(kind):
    pytest.importorskip("langgraph.graph")
    from wafer_sched.recovery.agent import run_recovery_agent
    p = (terminal_competition(m=1, count=1) if kind == "unbounded" else
         terminal_competition(m=1, process_times=[6,8], deadlines=[4,5], residencies=[1,2])
         if kind == "heterogeneous" else terminal_competition())
    result = run_recovery_agent(p, initial_seconds=0)
    assert result["status"] in {"FINITE", "UNBOUNDED"}
    rows = result["history"]
    assert rows[0]["result"]["status"] == "UNKNOWN"
    assert rows[1]["proposal"]["previous_status"] == "UNKNOWN"
    assert rows[1]["proposal"]["max_seconds"] > rows[0]["proposal"]["max_seconds"]
    assert rows[1]["proposal"]["query_tick"] == rows[0]["proposal"]["query_tick"]
    assert len({(h["proposal"]["phase"], h["proposal"]["query_tick"]) for h in rows}) >= 2
    assert result["best"]["verification"]["valid"]
    assert result["llm_calls"] == 0


def test_agent_budget_exhaustion_keeps_verified_incumbent():
    pytest.importorskip("langgraph.graph")
    from wafer_sched.recovery.agent import run_recovery_agent
    result = run_recovery_agent(terminal_competition(), initial_seconds=1, max_rounds=1)
    assert result["status"] == "UNKNOWN" and result["stop_reason"] == "budget_exhausted"
    assert result["best"]["verification"]["valid"]
    assert result["proven_infeasible_upper_seconds"] is None


def test_offline_agent_disables_inherited_network_tracing(monkeypatch):
    pytest.importorskip("langgraph.graph")
    import socket
    from wafer_sched.recovery.agent import run_recovery_agent
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    def no_network(*args, **kwargs):
        raise AssertionError("Offline recovery must not open a network connection")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = run_recovery_agent(terminal_competition(m=1), initial_seconds=1)
    assert result["status"] == "FINITE" and result["llm_calls"] == 0
