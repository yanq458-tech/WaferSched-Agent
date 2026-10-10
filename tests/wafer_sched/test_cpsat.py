"""Mathematical optima are accepted only after original-engine replay."""

from copy import deepcopy

import pytest

from wafer_sched import EquipmentConfig, Simulator, load_config
from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.cpsat_model import UnsupportedModel, build_model
from wafer_sched.cpsat_solver import SolverOptions, solve_schedule
from wafer_sched.cpsat_validator import validate_solution
from wafer_sched.policy_runner import run_policy
from wafer_sched.policies import FIFOPolicy
from wafer_sched.schedule_adapter import replay_schedule
from wafer_sched.stage4_metrics import proof_comparison


def tiny(count=1, *, process=5, times=(1, 1, 1), parallel=False, repeated=False):
    return EquipmentConfig.from_dict({
        "robot": dict(zip(("pick_seconds", "move_seconds", "place_seconds"), times)),
        "chambers": [{"id": "A", "processing_times": {"x": process, "y": 3}},
                     {"id": "B", "processing_times": {"x": process + 2}}],
        "wafers": [{"id": f"W{index+1}", "route": [
            {"recipe": "x", "chambers": ["A", "B"] if parallel else ["A"]},
            *([{"recipe": "y", "chambers": ["A"]}] if repeated else [])]}
                   for index in range(count)]})


def solve_and_check(config, expected=None):
    result = solve_schedule(config, SolverOptions(max_seconds=3, log_search=False))
    assert result.metadata["status"] == "OPTIMAL", result.metadata
    replay, report = validate_solution(config, result)
    assert report["valid"], report
    assert report["global_optimum_of_supported_instance"]
    assert result.metadata["relative_gap"] == 0
    if expected is not None:
        assert result.metadata["objective_seconds"] == expected
        assert report["actual_makespan_seconds"] == expected
    assert all(row["legal"]["valid"] for row in replay.decisions)
    return result, replay


def test_single_wafer_single_chamber_hand_optimum():
    result, replay = solve_and_check(tiny(), 11)  # 3 input + 5 process + 3 output.
    assert result.metadata["best_bound_seconds"] == 11
    assert replay.report["constraint_violations"] == 0


def test_two_wafers_same_chamber_optimum_includes_empty_reposition_and_blocking():
    _, replay = solve_and_check(tiny(2), 23)
    assert sum(w.stage for w in replay.simulator.state.wafers.values()) == 2
    assert replay.simulator.validate_state()


def test_original_three_wafer_proven_optimum_and_identical_engine_times():
    config = load_config(PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json")
    result, replay = solve_and_check(config, 47)
    comparison = proof_comparison(47, result.metadata, True)
    assert comparison["difference_to_proven_optimum_seconds"] == 0
    assert replay.simulator.completed


def test_same_chamber_consecutive_stages_merge_ownership_without_illegal_self_overlap():
    _, replay = solve_and_check(tiny(process=2, repeated=True), 13)
    wafer = replay.simulator.state.wafers["W1"]
    assert [(row["start"], row["end"]) for row in wafer.processing_records] == [(3, 5), (7, 10)]
    assert wafer.transfer_records[1]["source"] == wafer.transfer_records[1]["destination"] == "A"


def test_two_wafer_repeat_chamber_intervals_still_exclude_other_wafers():
    solve_and_check(tiny(count=2, process=2, repeated=True), 27)


def test_parallel_compatible_chambers_and_robot_circuit_nonoverlap():
    result, _ = solve_and_check(tiny(count=2, process=10, parallel=True))
    assignments = {entry["chamber"] for entry in result.schedule["processes"]}
    assert assignments == {"A", "B"}
    for left, right in zip(result.schedule["transfers"], result.schedule["transfers"][1:]):
        assert left["end_tick"] <= right["start_tick"]
        assert right["previous_position"] == left["destination"]


def test_long_transport_optimum_has_real_pick_move_place_time():
    result, _ = solve_and_check(tiny(process=5, times=(2, 7, 3)), 29)
    assert [entry["end_tick"] - entry["start_tick"] for entry in result.schedule["transfers"]] == [12, 12]


def test_directional_matrix_initial_position_and_exact_fractional_ticks():
    config = tiny(process=1.25, times=(.25, .5, .25)).to_dict()
    config["robot"].update(initial_position="B", travel_times=[
        {"source": "B", "destination": "LOAD", "seconds": 1.5},
        {"source": "A", "destination": "OUT", "seconds": 2}])
    # 1.5 empty positioning + 1 input + 1.25 process + 2.5 output = 6.25.
    result, _ = solve_and_check(EquipmentConfig.from_dict(config), 6.25)
    assert result.metadata["ticks_per_second"] == 4


def test_explicitly_known_release_table_is_offline_scope():
    config = tiny().to_dict()
    config["wafers"][0]["release_seconds"] = 5
    solve_and_check(EquipmentConfig.from_dict(config), 16)


def test_too_short_horizon_is_infeasible_restricted_model_not_physical_instance_claim():
    config = tiny()
    result = solve_schedule(config, SolverOptions(horizon_seconds=5, log_search=False))
    assert result.metadata["status"] == "INFEASIBLE" and result.schedule is None
    assert result.metadata["restricted_model"]
    replay, report = validate_solution(config, result)
    assert replay is None and report["valid"] is False


def test_zero_time_limit_unknown_is_not_feasible_or_optimal():
    result = solve_schedule(tiny(), SolverOptions(max_seconds=0, log_search=False))
    assert result.metadata["status"] == "UNKNOWN"
    assert result.schedule is None and result.metadata["objective_seconds"] is None
    assert result.metadata["relative_gap"] is None


def test_explicit_objective_bounds_scope_and_infeasibility():
    result = solve_schedule(tiny(), SolverOptions(objective_upper_seconds=10, log_search=False))
    assert result.metadata["status"] == "INFEASIBLE" and result.metadata["restricted_model"]


def test_future_faults_zero_pick_and_unrepresentable_time_are_rejected_not_ignored():
    config = tiny().to_dict()
    config["downtimes"] = [{"chamber": "A", "start": 2, "end": 4}]
    with pytest.raises(UnsupportedModel, match="Downtime"):
        build_model(EquipmentConfig.from_dict(config))
    with pytest.raises(UnsupportedModel, match="positive"):
        build_model(tiny(times=(0, 1, 1)))
    with pytest.raises(UnsupportedModel, match="exactly"):
        build_model(tiny(process=.25), ticks_per_second=1)
    with pytest.raises(UnsupportedModel, match="scale"):
        build_model(tiny(process=.000001))


def test_tampered_plan_fails_original_action_check_no_automatic_repair():
    config = tiny()
    result, _ = solve_and_check(config)
    corrupted = deepcopy(result.schedule)
    corrupted["transfers"][0]["destination"] = "B"
    replay = replay_schedule(config, corrupted)
    assert not replay.report["valid"]
    assert replay.report["constraint_violations"] == 1
    assert replay.report["issues"][0]["code"] == "route_order"
    assert replay.simulator.state.time == 0


def test_tampered_robot_overlap_and_process_prediction_fail_cross_validation():
    config = tiny(count=2)
    result, _ = solve_and_check(config)
    corrupted = deepcopy(result)
    corrupted.schedule["transfers"][1]["start_tick"] = corrupted.schedule["transfers"][0]["start_tick"]
    _, report = validate_solution(config, corrupted)
    assert report["valid"] is False
    assert any(issue["code"] == "plan_time_regression" for issue in report["issues"])
    corrupted = deepcopy(result)
    corrupted.schedule["processes"][0]["end_tick"] += 1
    _, report = validate_solution(config, corrupted)
    assert report["valid"] is False
    assert any(issue["code"] == "process_end_mismatch" for issue in report["issues"])


def test_incomplete_schedule_and_midrun_initialization_are_rejected():
    config = tiny()
    result, _ = solve_and_check(config)
    short = deepcopy(result.schedule)
    short["transfers"] = short["transfers"][:-1]
    assert replay_schedule(config, short).report["valid"] is False
    sim = Simulator(config)
    sim.submit(sim.legal_actions()[0])
    with pytest.raises(ValueError, match="initial"):
        replay_schedule(config, result.schedule, simulator=sim)


def test_verified_hint_replays_and_unverified_hint_is_rejected():
    config = tiny(count=2)
    hint = Simulator(config)
    with pytest.raises(ValueError, match="validated"):
        solve_schedule(config, incumbent=hint)
    run_policy(hint, FIFOPolicy())
    result = solve_schedule(config, SolverOptions(log_search=False), incumbent=hint)
    assert result.metadata["incumbent_hint"]
    assert validate_solution(config, result)[1]["valid"]


def test_feasible_bound_statistics_do_not_claim_an_optimum():
    metadata = {"status": "FEASIBLE", "best_bound_seconds": 10, "objective_seconds": 12,
                "restricted_model": False}
    comparison = proof_comparison(15, metadata, True)
    assert comparison["proven_optimum_seconds"] is None
    assert comparison["difference_to_verified_cp_incumbent_seconds"] == 3
    assert comparison["excess_over_lower_bound_seconds"] == 5


def test_small_independent_exhaustive_original_simulator_matches_cp_optimum():
    config = tiny(count=2, process=2, parallel=True)
    best, leaves = float("inf"), 0

    def visit(sim):
        nonlocal best, leaves
        if sim.state.time >= best:
            return
        while sim.state.robot.busy:
            assert sim.advance_next()
        if sim.completed:
            leaves += 1
            best = min(best, sim.state.time)
            return
        for action in sim.legal_actions():
            branch = deepcopy(sim)
            assert branch.submit(action)
            visit(branch)

    visit(Simulator(config))
    assert leaves >= 2
    result, _ = solve_and_check(config)
    assert result.metadata["objective_seconds"] == best


@pytest.mark.parametrize("options", [{"max_seconds": -1}, {"workers": 0}, {"seed": -1}])
def test_solver_configuration_rejects_invalid_budgets(options):
    with pytest.raises(ValueError):
        SolverOptions(**options)


def test_large_model_accepts_verified_incumbent_when_hint_is_fixed_for_compatibility_check():
    from ortools.sat.python import cp_model
    from wafer_sched.cpsat_model import add_verified_hint
    from wafer_sched.policies import SPTPolicy

    config = load_config(PROJECT_ROOT / "configs/wafer_sched/L_large.json")
    original = Simulator(config)
    assert run_policy(original, SPTPolicy(), max_time=2500).outcome["status"] == "completed"
    bundle = build_model(config)
    add_verified_hint(bundle, original)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    solver.parameters.fix_variables_to_their_hinted_value = True
    # This proves feasibility of the restricted hint, not global optimality.
    assert solver.solve(bundle.model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    for task in bundle.transfers:
        actual = original.state.wafers[task.wafer_id].transfer_records[task.stage]
        assert solver.value(task.start) / bundle.scale == actual["start"]
        assert solver.value(task.end) / bundle.scale == actual["end"]
    for task in bundle.processes:
        actual = original.state.wafers[task.wafer_id].processing_records[task.stage]
        assert bundle.locations[solver.value(task.chamber)] == actual["chamber"]
        assert solver.value(task.start) / bundle.scale == actual["start"]
        assert solver.value(task.end) / bundle.scale == actual["end"]
