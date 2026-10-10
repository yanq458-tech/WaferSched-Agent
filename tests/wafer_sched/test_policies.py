"""Check online information boundaries, exact rankings and physical replays."""

from copy import deepcopy
from dataclasses import asdict, replace, FrozenInstanceError
import gzip
import json
from pathlib import Path

import pytest

from wafer_sched import Action, EquipmentConfig, Simulator, load_config
from wafer_sched.artifacts import save_run
from wafer_sched.metrics import calculate_metrics
from wafer_sched.observation import ObservationBuilder, freeze, plain
from wafer_sched.policies.rules import (
    AdaptiveHeuristicPolicy, BottleneckAwarePolicy, ECTPolicy, FIFOPolicy,
    POLICIES, SPTPolicy, loads, make_policy, task_features,
)
from wafer_sched.policy_runner import run_policy
from wafer_sched.reporting import actual_intervals, plot_gantt, read_events
from wafer_sched.scenarios import study_scenarios

DEMO = Path(__file__).resolve().parents[2] / "configs/wafer_sched/minimal_demo.json"


@pytest.mark.parametrize("name", POLICIES)
@pytest.mark.parametrize("scenario,config,window", study_scenarios(), ids=lambda value: value if isinstance(value, str) else None)
def test_all_rules_finish_same_jobs_and_all_decisions_are_legal(name, scenario, config, window):
    simulator = Simulator(config)
    run = run_policy(simulator, make_policy(name), max_time=window)
    assert run.outcome["status"] == "completed"
    assert run.outcome["constraint_violations"] == 0
    assert simulator.validate_state()
    assert run.outcome["decision_count"] < 10 * len(config.wafers)
    for decision in run.decisions:
        assert decision["action"] in decision["legal_actions"]
        assert decision["observation"]["robot"]["busy"] is False
    for wafer_config in config.wafers:
        wafer = simulator.state.wafers[wafer_config.wafer_id]
        assert wafer.location == "OUT" and wafer.stage == len(wafer_config.route)
        assert len(wafer.transfer_records) == len(wafer_config.route) + 1
        for record, step in zip(wafer.processing_records, wafer_config.route):
            assert record["recipe"] == step.recipe and record["chamber"] in step.chambers
    if scenario == "D_parallel":
        chambers = {row["chamber"] for wafer in simulator.state.wafers.values() for row in wafer.processing_records}
        assert "CLEAN_ALT" in chambers


@pytest.mark.parametrize("name", POLICIES)
def test_policy_only_reads_detached_immutable_values(name):
    simulator = Simulator(load_config(DEMO))
    observation = ObservationBuilder().build(simulator)
    original = deepcopy(simulator.snapshot())
    trace = deepcopy(simulator.trace)
    action = make_policy(name).select_action(observation, simulator.legal_actions())
    assert simulator.validate_action(action)
    assert simulator.snapshot() == original and simulator.trace == trace
    with pytest.raises(TypeError):
        observation.wafers["W1"]["location"] = "OUT"
    with pytest.raises(TypeError):
        observation.wafers["W1"]["route"][0]["recipe"] = "fake"
    with pytest.raises(FrozenInstanceError):
        observation.time = 123
    assert not hasattr(observation, "__dict__")
    assert not hasattr(observation, "events")
    assert not hasattr(observation, "simulator")


@pytest.mark.parametrize("name", POLICIES)
def test_unannounced_releases_and_future_faults_cannot_change_policy_input(name):
    config = load_config(DEMO).to_dict()
    later = deepcopy(config)
    later["wafers"].append({"id": "SECRET_WAFER", "release_seconds": 100,
                             "route": [{"recipe": "clean", "chambers": ["CLEAN"]}]})
    later["downtimes"] = [{"chamber": "CLEAN", "start": 50, "end": 500}]
    first, second = Simulator(EquipmentConfig.from_dict(config)), Simulator(EquipmentConfig.from_dict(later))
    left, right = ObservationBuilder().build(first), ObservationBuilder().build(second)
    assert left == right
    assert "SECRET_WAFER" not in repr(right)
    # The explicit wait mask exposes that an event can advance time, not its identity/time.
    executable_left = tuple(action for action in first.legal_actions() if action.kind != "wait")
    executable_right = tuple(action for action in second.legal_actions() if action.kind != "wait")
    assert executable_left == executable_right
    assert make_policy(name).select_action(left, executable_left) == make_policy(name).select_action(right, executable_right)


@pytest.mark.parametrize("name", POLICIES)
def test_exact_single_wafer_time_and_replay(name):
    config = load_config(DEMO)
    config = replace(config, wafers=config.wafers[:1])
    first, second = Simulator(config, seed=7), Simulator(config, seed=7)
    left, right = run_policy(first, make_policy(name)), run_policy(second, make_policy(name))
    assert first.trace == second.trace and left.decisions == right.decisions
    metrics = calculate_metrics(first.trace)
    assert metrics["makespan_seconds"] == 19
    assert metrics["robot_action_seconds"] == 9
    assert metrics["average_waiting_seconds"] == 0
    assert metrics["blocking_seconds"] == 2
    first.run_until(80)
    metrics = calculate_metrics(first.trace)
    assert metrics["finite_batch_wph"] == 45
    assert metrics["robot_utilization"] == 9 / 80
    assert metrics["mean_chamber_utilization"] == 10 / 160
    assert metrics["makespan_seconds"] == 19


def ranking_example():
    config = EquipmentConfig.from_dict({
        "robot": {"pick_seconds": 1, "move_seconds": 1, "place_seconds": 1},
        "chambers": [{"id": "A", "processing_times": {"slow": 12, "fast": 2}},
                     {"id": "B", "processing_times": {"rinse": 5}}],
        "wafers": [{"id": "OLD", "route": [{"recipe": "slow", "chambers": ["A"]}]},
                   {"id": "NEW", "route": [{"recipe": "fast", "chambers": ["A"]}]}],
    })
    observation = ObservationBuilder().build(Simulator(config))
    wafers = plain(observation.wafers)
    wafers["OLD"]["task_ready_since"], wafers["NEW"]["task_ready_since"] = 1, 8
    return replace(observation, time=10, wafers=freeze(wafers))


def test_fifo_spt_ect_rank_actual_features_and_deterministic_ties():
    observation = ranking_example()
    actions = (Action.transfer("NEW", "A"), Action.transfer("OLD", "A"))
    assert FIFOPolicy().select_action(observation, actions).wafer_id == "OLD"
    assert SPTPolicy().select_action(observation, actions).wafer_id == "NEW"
    assert ECTPolicy().select_action(observation, actions).wafer_id == "NEW"
    features = task_features(observation, actions[0])
    assert features["transport_seconds"] == 3
    assert features["estimated_next_completion_seconds"] == 15
    assert features["waiting_age_seconds"] == 2
    assert FIFOPolicy().select_action(observation, actions) == FIFOPolicy().select_action(observation, actions[::-1])


def test_spt_output_priority_and_ect_empty_positioning():
    observation = ranking_example()
    wafers = plain(observation.wafers)
    wafers["OLD"].update(location="B", stage=1, task_ready_since=10)
    observation = replace(observation, wafers=freeze(wafers))
    output, feed = Action.unload("OLD"), Action.transfer("NEW", "A")
    assert SPTPolicy().select_action(observation, (feed, output)) == output
    features = task_features(observation, output)
    assert features["transport_seconds"] == 4  # LOAD->B empty + pick + B->OUT + place.
    assert features["next_process_seconds"] == 0


def test_bottleneck_logs_additive_score_components_and_workload():
    observation = ranking_example()
    assert loads(observation) == {"A": 14, "B": 0}
    policy = BottleneckAwarePolicy()
    policy.select_action(observation, (Action.transfer("NEW", "A"), Action.transfer("OLD", "A")))
    for candidate in policy.last_decision["candidates"]:
        parts = candidate["components"]
        assert parts["total"] == pytest.approx(sum(parts[key] for key in
                                                   ("unblock", "feed", "starvation", "age", "unload", "transport")))


@pytest.mark.parametrize("trigger,rule", [
    ("blocking_pressure", "bottleneck"), ("bottleneck_starvation", "bottleneck"),
    ("queue_pressure", "spt"), ("queue_and_robot_pressure", "ect"), ("normal_state", "fifo"),
])
def test_adaptive_each_feedback_trigger(trigger, rule):
    observation = ranking_example()
    chambers, wafers, history = plain(observation.chambers), plain(observation.wafers), plain(observation.history)
    if trigger == "blocking_pressure":
        chambers["B"]["status"] = "blocked"
    if trigger == "bottleneck_starvation":
        chambers["A"]["idle_age_seconds"] = 3  # reference12, ratio.25 at threshold.
    if trigger in {"queue_pressure", "queue_and_robot_pressure"}:
        for index in range(2):
            wafers[f"EXTRA{index}"] = deepcopy(wafers["NEW"])
        history["robot_utilization"] = .65 if trigger == "queue_and_robot_pressure" else .64
    observation = replace(observation, chambers=freeze(chambers), wafers=freeze(wafers), history=freeze(history))
    policy = AdaptiveHeuristicPolicy()
    policy.select_action(observation, (Action.transfer("NEW", "A"),))
    assert policy.last_decision["trigger"] == trigger
    assert policy.last_decision["rule"] == rule
    assert policy.last_decision["switched"]


def test_historical_blocking_feedback_and_real_rule_changes():
    observation = ranking_example()
    chambers = plain(observation.chambers)
    chambers["B"]["status"] = "blocked"
    chambers["C"] = deepcopy(chambers["A"])
    history = plain(observation.history)
    history["blocking_rate"] = .12
    observation = replace(observation, chambers=freeze(chambers), history=freeze(history))
    policy = AdaptiveHeuristicPolicy()
    policy.select_action(observation, (Action.transfer("NEW", "A"),))
    assert policy.last_decision["trigger"] == "blocking_pressure"  # current1/3 < .5, past triggers.
    _, config, window = study_scenarios()[1]
    run = run_policy(Simulator(config), AdaptiveHeuristicPolicy(), max_time=window)
    assert len({row["explanation"]["rule"] for row in run.decisions}) >= 3
    assert len({row["explanation"]["trigger"] for row in run.decisions}) >= 3


def test_incremental_history_matches_actual_event_integrals():
    simulator = Simulator(load_config(DEMO))
    run_policy(simulator, FIFOPolicy())
    observation = ObservationBuilder().build(simulator)
    metrics = calculate_metrics(simulator.trace)
    assert plain(observation.history["chamber_processing_seconds"]) == metrics["chamber_processing_seconds"]
    assert plain(observation.history["chamber_blocking_seconds"]) == metrics["chamber_blocking_seconds"]
    assert observation.history["robot_utilization"] == metrics["robot_utilization"]


def test_wait_has_bounded_steps_and_invalid_policy_is_not_repaired():
    class InvalidPolicy:
        name = "invalid"

        def select_action(self, observation, legal_actions):
            return Action.unload("missing")

    simulator = Simulator(load_config(DEMO))
    snapshot = simulator.snapshot()
    run = run_policy(simulator, InvalidPolicy())
    assert run.outcome["status"] == "invalid_policy" and run.outcome["constraint_violations"] == 1
    assert simulator.snapshot() == snapshot
    assert run_policy(Simulator(load_config(DEMO)), FIFOPolicy(), max_steps=1).outcome["reason"] == "step_budget"
    delayed = load_config(DEMO).to_dict()
    for wafer in delayed["wafers"]:
        wafer["release_seconds"] = 10
    simulator = Simulator(EquipmentConfig.from_dict(delayed))
    run = run_policy(simulator, FIFOPolicy(), max_time=5)
    assert run.outcome["reason"] == "time_budget" and simulator.state.time == 5
    assert len(run.decisions) == 1 and run.decisions[0]["action"]["kind"] == "wait"


def test_saved_compressed_full_trace_recomputes_metrics_and_plot_intervals(tmp_path):
    simulator = Simulator(load_config(DEMO))
    run = run_policy(simulator, FIFOPolicy())
    simulator.run_until(80)
    directory = save_run(simulator, run.outcome, run_id="policy-test", output_root=tmp_path, compress_events=True)
    assert not (directory / "events.json").exists()
    trace = read_events(directory)
    assert trace == simulator.trace
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    assert calculate_metrics(trace) == metrics
    segments = actual_intervals(trace)
    assert sum(item["end"] - item["start"] for item in segments["ROBOT"]) == metrics["robot_action_seconds"]
    for chamber in metrics["chamber_processing_seconds"]:
        assert sum(item["end"] - item["start"] for item in segments[chamber] if item["phase"] == "processing") == metrics["chamber_processing_seconds"][chamber]
    with gzip.open(directory / "events.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream)["schema_version"] == 1
    plot_gantt(directory, "test / FIFO")
    assert (directory / "gantt.png").stat().st_size > 10000
    metadata = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    assert metadata["driver"] == "policy_runner"
    assert "policies/rules.py" in metadata["core_source_sha256"]


def test_empty_catalogue_and_non_macro_diagnostic_actions_are_explicit_errors():
    observation = ranking_example()
    for name in POLICIES:
        with pytest.raises(ValueError):
            make_policy(name).select_action(observation, ())
        with pytest.raises(ValueError):
            make_policy(name).select_action(observation, (Action.pick("OLD", "LOAD"),))
        assert asdict(make_policy(name).select_action(observation, (Action.wait(),)))["kind"] == "wait"


def test_policy_runner_reports_physical_cycle_without_advancing_forever():
    config = EquipmentConfig.from_dict({
        "robot": {"pick_seconds": 1, "move_seconds": 1, "place_seconds": 1},
        "chambers": [{"id": "A", "processing_times": {"a": 2}},
                     {"id": "B", "processing_times": {"b": 2}}],
        "wafers": [{"id": "W1", "route": [{"recipe": "a", "chambers": ["A"]},
                                               {"recipe": "b", "chambers": ["B"]}]},
                   {"id": "W2", "route": [{"recipe": "b", "chambers": ["B"]},
                                               {"recipe": "a", "chambers": ["A"]}]}],
    })
    simulator = Simulator(config)
    run = run_policy(simulator, FIFOPolicy())
    assert run.outcome["status"] == "deadlocked" and simulator.state.time == 9
    assert run.outcome["reason"]["code"] == "no_progress_action_or_future_event"
    assert simulator.validate_state()
    assert run.outcome["decision_count"] < 10


@pytest.mark.parametrize("name", POLICIES)
def test_policy_handles_unannounced_fault_pause_and_delayed_arrival(name):
    config = load_config(DEMO).to_dict()
    config["wafers"] = config["wafers"][:1]
    config["wafers"][0]["release_seconds"] = 5
    config["downtimes"] = [{"chamber": "CLEAN", "start": 9, "end": 13}]
    simulator = Simulator(EquipmentConfig.from_dict(config))
    run = run_policy(simulator, make_policy(name))
    metrics = calculate_metrics(simulator.trace)
    assert run.outcome["status"] == "completed"
    assert metrics["makespan_seconds"] == 28
    assert metrics["chamber_processing_seconds"] == {"CLEAN": 4, "RINSE": 6}
    assert metrics["robot_action_seconds"] == 9
    assert metrics["average_waiting_seconds"] == 4
    assert "W1" not in run.decisions[0]["observation"]["wafers"]
    for decision in run.decisions:
        assert "events" not in repr(decision["observation"])
