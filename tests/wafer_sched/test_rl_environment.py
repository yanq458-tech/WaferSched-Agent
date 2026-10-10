"""Concrete physical times, masks, event equivalence and termination semantics."""
from wafer_sched.infrastructure.provenance import assert_original_or_migrated

from dataclasses import replace
import json

import gymnasium as gym
from gymnasium.utils.env_checker import check_env
import numpy as np
import pytest

from wafer_sched import Action, EquipmentConfig, Simulator, load_config
from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.metrics import calculate_metrics
from wafer_sched.observation import ObservationBuilder
from wafer_sched.policies import FIFOPolicy
from wafer_sched.policy_runner import run_policy
from wafer_sched.rl import EncodingSchema, ObservationEncoder, WaferSchedulingEnv
from wafer_sched.rl.evaluation import audit_mask_against_checker


def tiny(*, count=1, process=5, parallel=False):
    return EquipmentConfig.from_dict({"robot": {"pick_seconds": 1, "move_seconds": 1, "place_seconds": 1},
                                      "chambers": [{"id": "A", "processing_times": {"x": process}},
                                                   {"id": "B", "processing_times": {"x": process}}],
                                      "wafers": [{"id": f"W{i+1}", "route": [{"recipe": "x", "chambers": ["A", "B"] if parallel else ["A"]}]}
                                                 for i in range(count)]})


def drive(env, seed=0, policy=None):
    vector, _ = env.reset(seed=seed)
    policy = policy or FIFOPolicy()
    transitions = []
    for _ in range(env.max_decisions):
        action = policy.select_action(env.observation, env.simulator.legal_actions())
        transitions.append(env.step(env.action_encoder.index(action, env.observation)))
        vector, _, terminated, truncated, _ = transitions[-1]
        assert env.observation_space.contains(vector)
        if terminated or truncated:
            return transitions
    pytest.fail("No termination within the declared decision budget")


def test_gymnasium_interface_with_explicit_masked_checker_sampling():
    env = WaferSchedulingEnv(tiny())
    env.reset(seed=0)
    initial_mask = env.action_masks().astype(np.int8)

    class MaskedCheckerSpace(gym.spaces.Discrete):
        # Official checker samples before resetting in its determinism test.
        # Sample from the initial state's legal mask. Only test sampling is adapted;
        # production illegal actions still raise, and the physical environment is unchanged.
        def sample(self, mask=None, probability=None):
            return super().sample(initial_mask if mask is None else mask, probability)

    env.action_space = MaskedCheckerSpace(env.action_space.n)
    check_env(env, skip_render_check=True)
    assert isinstance(env.render(), str)


def test_single_wafer_hand_completion_reward_and_metrics():
    env = WaferSchedulingEnv(tiny())
    transitions = drive(env)
    assert len(transitions) == 2
    assert [row[4]["delta_seconds"] for row in transitions] == [8, 3]
    assert transitions[-1][2:4] == (True, False)
    metrics = calculate_metrics(env.simulator.trace)
    assert metrics["makespan_seconds"] == 11
    assert metrics["robot_action_seconds"] == 6
    assert metrics["blocking_seconds"] == 1
    assert metrics["average_waiting_seconds"] == 0
    totals = transitions[-1][4]["episode_summary"]["reward_totals"]
    assert totals["raw"]["completed_wafers"] == 1
    assert sum(row[1] for row in transitions) == pytest.approx(10 - .22 - .006 - .0005)
    assert sum(totals["weighted"].values()) == pytest.approx(env.total_reward)


@pytest.mark.parametrize("filename", ["minimal_demo.json", "S_small.json", "F_competition.json",
                                      "G_dual_bottleneck.json", "H_heterogeneous.json", "rl/T_noalt.json"])
def test_fixed_dimensions_complete_tasks_and_original_engine_equality(filename):
    config = load_config(PROJECT_ROOT / "configs/wafer_sched" / filename)
    env = WaferSchedulingEnv(config)
    transitions = drive(env)
    sim = Simulator(config)
    original = run_policy(sim, FIFOPolicy())
    assert original.outcome["status"] == "completed"
    assert env.simulator.trace == sim.trace
    assert transitions[-1][4]["episode_summary"]["completion_rate"] == 1
    assert env.observation_encoder.encode(env.observation).shape == (588,)
    assert not env.action_masks().any()
    assert env.simulator.validate_state()
    totals = env.reward_totals["raw"]
    metrics = calculate_metrics(sim.trace)
    assert totals["elapsed_seconds"] == metrics["makespan_seconds"]
    assert totals["waiting_wafer_seconds"] == pytest.approx(sum(metrics["wafer_waiting_seconds"].values()))
    assert totals["blocking_chamber_seconds"] == pytest.approx(metrics["blocking_seconds"])
    assert totals["robot_seconds"] == pytest.approx(metrics["robot_action_seconds"])


def test_mask_all_indices_agrees_independently_with_original_constraint_checker():
    env = WaferSchedulingEnv(tiny(count=2, parallel=True))
    env.reset(seed=0)
    for _ in range(10):
        audit = audit_mask_against_checker(env.simulator, env.observation, env.action_encoder)
        assert audit["checked_indices"] == 41
        assert audit["false_positive"] == audit["false_negative"] == 0
        legal = env.simulator.legal_actions()
        table = env.action_encoder.catalogue(env.observation, legal)
        assert len(table) == len(legal) == int(env.action_masks().sum())
        for index, operation in table.items():
            assert env.action_encoder.decode(index, env.observation, legal) == operation
        operation = FIFOPolicy().select_action(env.observation, legal)
        _, _, terminated, truncated, _ = env.step(env.action_encoder.index(operation, env.observation))
        if terminated or truncated:
            break
    assert env.simulator.completed


@pytest.mark.parametrize("action", [0, -1, 40, 41, 1.5, True])
def test_illegal_actions_rejected_without_any_state_or_log_change(action):
    env = WaferSchedulingEnv(tiny())
    env.reset(seed=0)
    before, trace = env.simulator.snapshot(), list(env.simulator.trace)
    with pytest.raises(ValueError):
        env.step(action)
    assert env.simulator.snapshot() == before
    assert env.simulator.trace == trace
    assert env.decision_count == env.mask_checks == 0


def test_action_indices_stable_when_input_order_changes():
    config = tiny(count=2, parallel=True)
    left, right = WaferSchedulingEnv(config), WaferSchedulingEnv(replace(config, wafers=tuple(reversed(config.wafers)), chambers=tuple(reversed(config.chambers))))
    a, _ = left.reset(seed=0)
    b, _ = right.reset(seed=0)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(left.action_masks(), right.action_masks())
    action = Action.transfer("W2", "B")
    assert left.action_encoder.index(action, left.observation) == right.action_encoder.index(action, right.observation)


def test_read_only_encoding_contains_no_hidden_future_events():
    config = tiny()
    raw = config.to_dict()
    raw["downtimes"] = [{"chamber": "A", "start": 100, "end": 110}]
    first = Simulator(EquipmentConfig.from_dict(raw))
    raw["downtimes"] = [{"chamber": "A", "start": 200, "end": 240}]
    second = Simulator(EquipmentConfig.from_dict(raw))
    encoder = ObservationEncoder()
    a, b = ObservationBuilder().build(first), ObservationBuilder().build(second)
    np.testing.assert_array_equal(encoder.encode(a), encoder.encode(b))
    assert not hasattr(a, "events") and not hasattr(encoder, "simulator")
    before = first.snapshot()
    encoder.encode(a)
    assert first.snapshot() == before
    with pytest.raises(TypeError):
        a.robot["position"] = "A"


def test_route_and_travel_information_are_present_not_just_current_stage():
    config = tiny()
    extended = replace(config.wafers[0], route=config.wafers[0].route * 2)
    alternate = replace(config, wafers=(extended,))
    a, b = WaferSchedulingEnv(config), WaferSchedulingEnv(alternate)
    x, _ = a.reset(seed=0)
    y, _ = b.reset(seed=0)
    assert not np.array_equal(x, y)
    raw = config.to_dict()
    raw["robot"]["travel_times"] = [{"source": "A", "destination": "OUT", "seconds": 6}]
    z, _ = WaferSchedulingEnv(EquipmentConfig.from_dict(raw)).reset(seed=0)
    assert not np.array_equal(x, z)


@pytest.mark.parametrize("field,value", [("max_wafers", 1), ("max_chambers", 1)])
def test_excess_capacity_rejected_instead_of_truncating(field, value):
    schema = EncodingSchema(**{field: value})
    with pytest.raises(ValueError, match="capacity"):
        WaferSchedulingEnv(tiny(count=2), schema=schema)


@pytest.mark.parametrize("change", ["downtime", "release", "zero_pick"])
def test_nonmarkov_scope_rejected_explicitly(change):
    raw = tiny().to_dict()
    if change == "downtime":
        raw["downtimes"] = [{"chamber": "A", "start": 5, "end": 10}]
    elif change == "release":
        raw["wafers"][0]["release_seconds"] = 1
    else:
        raw["robot"]["pick_seconds"] = 0
    with pytest.raises(ValueError):
        WaferSchedulingEnv(EquipmentConfig.from_dict(raw))


def test_same_seed_scenario_sampling_rewards_and_events_reproducible():
    configs = [tiny(), tiny(count=2)]
    first, second = WaferSchedulingEnv(configs), WaferSchedulingEnv(configs)
    a, b = drive(first, seed=7), drive(second, seed=7)
    assert first.scenario_index == second.scenario_index
    assert first.simulator.trace == second.simulator.trace
    assert [(x[1], x[2], x[3], x[4]) for x in a] == [(x[1], x[2], x[3], x[4]) for x in b]


def test_time_truncation_retains_current_busy_mission_and_no_overshoot():
    env = WaferSchedulingEnv(tiny(), max_simulation_seconds=.5)
    env.reset(seed=0)
    operation = Action.transfer("W1", "A")
    _, _, terminated, truncated, info = env.step(env.action_encoder.index(operation, env.observation))
    assert (terminated, truncated) == (False, True)
    assert env.simulator.state.time == .5
    assert env.observation.robot["busy"]
    assert env.observation.robot["source"] == "LOAD"
    assert env.observation.robot["destination"] == "A"
    assert env.observation.robot["remaining_action_seconds"] == .5
    assert info["episode_summary"]["metrics"]["makespan_seconds"] is None
    assert env.simulator.validate_state()


def test_decision_budget_truncation_and_complete_at_exact_time_boundary():
    limited = WaferSchedulingEnv(tiny(), max_decisions=1)
    final = drive(limited)[-1]
    assert final[2:4] == (False, True)
    assert final[4]["termination_reason"] == "decision_budget"
    exact = WaferSchedulingEnv(tiny(), max_simulation_seconds=11)
    final = drive(exact)[-1]
    assert final[2:4] == (True, False)
    assert final[4]["termination_reason"] == "completed"
    with pytest.raises(RuntimeError, match="ended"):
        exact.step(0)


def test_same_timestamp_process_completions_settled_before_decision():
    raw = tiny(count=2, parallel=True).to_dict()
    raw["chambers"][0]["processing_times"]["x"] = 10
    raw["chambers"][1]["processing_times"]["x"] = 6
    env = WaferSchedulingEnv(EquipmentConfig.from_dict(raw))
    env.reset(seed=0)
    for action in (Action.transfer("W1", "A"), Action.transfer("W2", "B")):
        env.step(env.action_encoder.index(action, env.observation))
    assert env.simulator.state.time == 13
    rows = [row for row in env.simulator.trace if row["event"] == "ChamberProcessComplete"]
    assert [r["time"] for r in rows] == [13, 13]
    assert {env.observation.chambers[key]["status"] for key in ("A", "B")} == {"blocked"}
    assert env.action_masks()[env.action_encoder.index(Action.unload("W1"), env.observation)]
    assert env.action_masks()[env.action_encoder.index(Action.unload("W2"), env.observation)]


def test_cycle_deadlock_is_natural_terminal_with_reason_and_original_records():
    raw = tiny(count=2, process=10).to_dict()
    raw["wafers"][0]["route"] = [{"recipe": "x", "chambers": ["A"]}, {"recipe": "x", "chambers": ["B"]}]
    raw["wafers"][1]["route"] = [{"recipe": "x", "chambers": ["B"]}, {"recipe": "x", "chambers": ["A"]}]
    env = WaferSchedulingEnv(EquipmentConfig.from_dict(raw))
    env.reset(seed=0)
    for action in (Action.transfer("W1", "A"), Action.transfer("W2", "B")):
        result = env.step(env.action_encoder.index(action, env.observation))
    assert result[2:4] == (True, False)
    assert result[4]["termination_reason"] == "deadlocked"
    assert env.simulator.state.time == 17
    assert env.simulator.state.deadlock["code"] == "no_progress_action_or_future_event"
    assert env.reward_totals["weighted"]["deadlock"] == -10
    assert env.simulator.validate_state()


def test_stage_three_four_results_and_original_modules_unchanged():
    hashes = json.loads((PROJECT_ROOT / "docs/wafer_sched_stage5_preservation.json").read_text(encoding="utf-8"))
    assert len(hashes) >= 1233
    for path, expected in hashes.items():
        assert_original_or_migrated(path, expected)
