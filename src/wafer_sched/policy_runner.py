"""Trusted execution boundary; policies receive no engine references."""

from dataclasses import asdict, dataclass
from time import perf_counter
import math

from .observation import ObservationBuilder, plain
from .simulator import Simulator
from .policies import Policy


@dataclass
class PolicyRun:
    outcome: dict
    decisions: list[dict]


def run_policy(simulator: Simulator, policy: Policy, *, max_steps=100000, max_time=100000.0) -> PolicyRun:
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    if not math.isfinite(max_time) or max_time < 0:
        raise ValueError("max_time must be nonnegative and finite")
    builder, decisions, elapsed = ObservationBuilder(), [], 0.0

    def finish(status, reason=None, violations=0):
        return PolicyRun({"status": status, "reason": reason, "driver": "policy_runner",
                          "policy": policy.name, "constraint_violations": violations,
                          "policy_execution_seconds": elapsed, "decision_count": len(decisions)}, decisions)

    for _ in range(max_steps):
        if simulator.completed:
            return finish("completed")
        if simulator.state.time >= max_time:
            return finish("truncated", "time_budget")
        # Busy-robot microevents are execution, not new scheduling decisions.
        if simulator.state.robot.busy:
            if not simulator.state.events:
                return finish("deadlocked", simulator.detect_deadlock())
            if simulator.state.events[0].time > max_time:
                simulator.run_until(max_time)
                return finish("truncated", "time_budget")
            simulator.advance_next()
            continue
        legal = simulator.legal_actions()
        if not legal:
            return finish("deadlocked", simulator.detect_deadlock())
        observation = builder.build(simulator)
        started = perf_counter()
        action = policy.select_action(observation, legal)
        elapsed += perf_counter() - started
        if action not in legal or not simulator.validate_action(action):
            return finish("invalid_policy", "selected_action_outside_legal_catalogue", 1)
        decisions.append({"index": len(decisions), "time": observation.time,
                          "action": asdict(action), "observation": {
                              "robot": plain(observation.robot), "chambers": plain(observation.chambers),
                              "wafers": plain(observation.wafers), "history": plain(observation.history),
                              "completed_count": observation.completed_count},
                          "legal_actions": [asdict(item) for item in legal],
                          "explanation": plain(getattr(policy, "last_decision", {}))})
        if action.kind == "wait" and simulator.state.events[0].time > max_time:
            simulator.run_until(max_time)
            return finish("truncated", "time_budget")
        result = simulator.submit(action)
        if not result:
            return finish("invalid_policy", result.reason, 1)
    return finish("truncated", "step_budget")
