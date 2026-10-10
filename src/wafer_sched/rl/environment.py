"""Gymnasium boundary over the existing Simulator, with variable event durations."""

from dataclasses import asdict, replace
import math

import gymnasium as gym
import numpy as np

from ..config import EquipmentConfig
from ..metrics import calculate_metrics
from ..observation import ObservationBuilder, freeze
from ..simulator import Simulator
from .encoding import ActionEncoder, EncodingSchema, ObservationEncoder
from .reward import RewardCalculator, RewardWeights


def validate_static_config(config, schema):
    if not isinstance(config, EquipmentConfig):
        raise TypeError("Expected the original EquipmentConfig")
    if config.downtimes or any(w.release_seconds != 0 for w in config.wafers):
        raise ValueError("Stage-five Markov environment supports only static, all-at-zero released batches")
    if config.robot.pick_seconds <= 0 or config.robot.place_seconds <= 0:
        raise ValueError("RL macro actions require positive pick/place duration")
    if (len(config.wafers) > schema.max_wafers or len(config.chambers) > schema.max_chambers
            or any(len(w.route) > schema.max_stages for w in config.wafers)):
        raise ValueError("Equipment exceeds encoding capacity; legal actions will not be truncated")


class CurrentObservationBuilder(ObservationBuilder):
    """Supplement the public view with the currently executing robot mission only."""

    def build(self, simulator):
        observation = super().build(simulator)
        current = simulator.state.robot
        robot = dict(observation.robot)
        robot.update(active_wafer=current.active_wafer, source=current.source,
                     destination=current.destination, high_level=current.high_level,
                     remaining_action_seconds=(max(0.0, current.phase_end - observation.time)
                                               if current.phase_end is not None else 0.0))
        return replace(observation, robot=freeze(robot))


class WaferSchedulingEnv(gym.Env):
    metadata = {"render_modes": ["ansi"]}

    def __init__(self, configs, *, schema=EncodingSchema(), reward_weights=RewardWeights(),
                 max_simulation_seconds=2000.0, max_decisions=512, render_mode=None):
        super().__init__()
        self.configs = (configs,) if isinstance(configs, EquipmentConfig) else tuple(configs)
        if not self.configs:
            raise ValueError("At least one training scenario is required")
        for config in self.configs:
            validate_static_config(config, schema)
        if isinstance(max_simulation_seconds, bool) or not math.isfinite(max_simulation_seconds) or max_simulation_seconds <= 0:
            raise ValueError("max_simulation_seconds must be finite and positive")
        if type(max_decisions) is not int or max_decisions <= 0:
            raise ValueError("max_decisions must be a positive integer")
        if render_mode not in {None, "ansi"}:
            raise ValueError("Only ansi rendering is supported")
        self.schema, self.reward_weights = schema, reward_weights
        self.max_simulation_seconds, self.max_decisions = max_simulation_seconds, max_decisions
        self.render_mode = render_mode
        self.observation_encoder, self.action_encoder = ObservationEncoder(schema), ActionEncoder(schema)
        self.reward_calculator = RewardCalculator(reward_weights)
        self.observation_space = gym.spaces.Box(0.0, 1.0, shape=(schema.observation_size,), dtype=np.float32)
        self.action_space = gym.spaces.Discrete(schema.action_count)
        self.simulator = None
        self.ended = False

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        options = options or {}
        if set(options) - {"scenario_index"}:
            raise ValueError("Unknown reset options")
        index = options.get("scenario_index", int(self.np_random.integers(len(self.configs))))
        if type(index) is not int or not 0 <= index < len(self.configs):
            raise ValueError("Invalid scenario_index")
        self.scenario_index = index
        self.simulator = Simulator(self.configs[index], seed=seed if seed is not None else 0)
        self.builder = CurrentObservationBuilder()
        self.decision_count, self.total_reward, self.episode_decisions = 0, 0.0, []
        self.reward_totals = {"raw": {}, "weighted": {}}
        self.mask_checks, self.mask_mismatches = 0, 0
        self.ended = False
        self.observation = self.builder.build(self.simulator)
        return self.observation_encoder.encode(self.observation), {"scenario": self.simulator.config.name}

    def _require_reset(self):
        if self.simulator is None:
            raise RuntimeError("Call reset before using the environment")

    def action_masks(self):
        self._require_reset()
        if self.ended:
            return np.zeros(self.schema.action_count, dtype=bool)
        return self.action_encoder.mask(self.observation, self.simulator.legal_actions())

    def _advance_to_decision(self):
        automatic_waits = 0
        while not self.simulator.completed:
            sim = self.simulator
            if sim.state.time >= self.max_simulation_seconds:
                return False, True, "time_budget", automatic_waits
            legal = sim.legal_actions()
            if not sim.state.robot.busy and any(a.kind != "wait" for a in legal):
                return False, False, None, automatic_waits
            # Queue access stays inside this trusted execution boundary, never in an encoder/policy.
            if not sim.state.events:
                sim.detect_deadlock()
                return True, False, "deadlocked", automatic_waits
            if sim.state.events[0].time > self.max_simulation_seconds:
                sim.run_until(self.max_simulation_seconds)
                return False, True, "time_budget", automatic_waits
            if sim.state.robot.busy:
                sim.advance_next()
            else:
                wait = next(a for a in legal if a.kind == "wait")
                assert sim.submit(wait)
                automatic_waits += 1
        return True, False, "completed", automatic_waits

    def step(self, action):
        self._require_reset()
        if self.ended:
            raise RuntimeError("Episode has ended; call reset")
        sim = self.simulator
        legal = sim.legal_actions()
        # Reject before modifying any physical state, clock, event, or episode counter.
        operation = self.action_encoder.decode(action, self.observation, legal)
        result = sim.validate_action(operation)
        if not result:
            raise ValueError(f"Illegal action: {result.code}: {result.reason}")
        mask = self.action_encoder.mask(self.observation, legal)
        start_index, start_time = len(sim.trace) - 1, sim.state.time
        self.mask_checks += 1
        self.mask_mismatches += int(not mask[int(action)])
        self.decision_count += 1
        if operation.kind == "wait" and sim.state.events[0].time > self.max_simulation_seconds:
            sim.run_until(self.max_simulation_seconds)
        else:
            result = sim.submit(operation)
            if not result:
                raise RuntimeError(f"Constraint checker changed its conclusion: {result}")
        terminated, truncated, reason, automatic_waits = self._advance_to_decision()
        if not terminated and not truncated and self.decision_count >= self.max_decisions:
            truncated, reason = True, "decision_budget"
        reward, components = self.reward_calculator.calculate(sim.trace, start_index, deadlocked=reason == "deadlocked")
        self.total_reward += reward
        for group, values in components.items():
            for key, value in values.items():
                self.reward_totals[group][key] = self.reward_totals[group].get(key, 0.0) + value
        self.ended = terminated or truncated
        self.observation = self.builder.build(sim)
        decision = {"index": self.decision_count - 1, "time": start_time, "end_time": sim.state.time,
                    "action_index": int(action), "action": asdict(operation),
                    "legal_action_indices": np.flatnonzero(mask).tolist(),
                    "mask_legal_count": int(mask.sum()), "mask_valid": bool(mask[int(action)]),
                    "automatic_event_waits": automatic_waits, "reward": reward,
                    "reward_components": components}
        self.episode_decisions.append(decision)
        info = {"scenario": sim.config.name, "delta_seconds": sim.state.time - start_time,
                "reward_components": components, "termination_reason": reason,
                "mask_valid": bool(mask[int(action)]), "mask_legal_count": int(mask.sum()),
                "automatic_event_waits": automatic_waits}
        if self.ended:
            metrics = calculate_metrics(sim.trace)
            info["episode_summary"] = {"scenario": sim.config.name, "return": self.total_reward,
                                       "decisions": self.decision_count, "reason": reason,
                                       "terminated": terminated, "truncated": truncated,
                                       "completion_rate": metrics["completed_wafers"] / len(sim.config.wafers),
                                       "mask_checks": self.mask_checks, "mask_mismatches": self.mask_mismatches,
                                       "constraint_violations": 0, "reward_totals": self.reward_totals, "metrics": metrics}
        return self.observation_encoder.encode(self.observation), reward, terminated, truncated, info

    def render(self):
        self._require_reset()
        return (f"t={self.simulator.state.time:g}s robot={dict(self.observation.robot)} "
                f"completed={self.observation.completed_count}/{len(self.observation.wafers)} "
                f"chambers={ {key: dict(value) for key, value in self.observation.chambers.items()} }")
