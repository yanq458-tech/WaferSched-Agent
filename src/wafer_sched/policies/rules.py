"""Explainable scores use observed jobs, nominal durations and actual past only."""

from dataclasses import asdict, dataclass
from typing import Protocol

from ..actions import Action
from ..observation import Observation


class Policy(Protocol):
    name: str

    def select_action(self, observation: Observation, legal_actions: tuple[Action, ...]) -> Action: ...


def travel(observation, source, destination):
    if source == destination:
        return 0.0
    return next((duration for left, right, duration in observation.robot["travel_times"]
                 if (left, right) == (source, destination)), observation.robot["move_seconds"])


def task_features(observation, action):
    wafer = observation.wafers[action.wafer_id]
    source = wafer["location"]
    robot = observation.robot
    duration = (travel(observation, robot["position"], source) + robot["pick_seconds"]
                + travel(observation, source, action.destination) + robot["place_seconds"])
    process = (0.0 if action.kind == "unload" else observation.chambers[action.destination][
        "processing_times"][wafer["route"][wafer["stage"]]["recipe"]])
    return {
        "waiting_age_seconds": observation.time - wafer["task_ready_since"],
        "transport_seconds": duration, "next_process_seconds": process,
        "estimated_next_completion_seconds": observation.time + duration + process,
        "unload": float(action.kind == "unload"),
        "source_blocked": float(source in observation.chambers
                                and observation.chambers[source]["status"] == "blocked"),
    }


def loads(observation):
    """Split remaining nominal service equally among eligible parallel chambers.

    This is a workload proxy, not an exact capacity/critical-path calculation.
    Includes known remaining current processing; excludes completed operations.
    """
    result = {key: 0.0 for key in observation.chambers}
    for wafer in observation.wafers.values():
        if wafer["completed"]:
            continue
        for index, step in enumerate(wafer["route"][wafer["stage"]:], wafer["stage"]):
            if index == wafer["stage"] and wafer["status"] in {"processing", "paused"}:
                result[wafer["location"]] += observation.chambers[wafer["location"]]["remaining_seconds"]
            else:
                for chamber in step["chambers"]:
                    result[chamber] += observation.chambers[chamber]["processing_times"][step["recipe"]] / len(step["chambers"])
    return result


def reference_time(observation):
    return max(1.0, max((duration for chamber in observation.chambers.values()
                        for duration in chamber["processing_times"].values()), default=1.0))


class ScoredPolicy:
    name = "base"

    def __init__(self):
        self.last_decision = {}

    def score(self, observation, action, features):
        raise NotImplementedError

    def select_action(self, observation, legal_actions):
        if not legal_actions:
            raise ValueError("Policy requires a nonempty simulator-generated catalogue")
        actions = [action for action in legal_actions if action.kind != "wait"]
        if not actions:
            action = next(action for action in legal_actions if action.kind == "wait")
            self.last_decision = {"rule": self.name, "reason": "no_executable_transfer_event_wait", "candidates": []}
            return action
        if any(action.kind not in {"transfer", "unload"} for action in actions):
            raise ValueError("Rule benchmarks require complete-transfer actions")
        candidates = []
        for action in actions:
            features = task_features(observation, action)
            priority, components = self.score(observation, action, features)
            candidates.append((priority + (action.wafer_id, action.destination), action,
                               {"action": asdict(action), "features": features,
                                "priority": list(priority), "components": components}))
        selected = min(candidates, key=lambda item: item[0])
        self.last_decision = {"rule": self.name, "reason": "minimum_lexicographic_priority",
                              "candidates": [item[2] for item in candidates]}
        return selected[1]


class FIFOPolicy(ScoredPolicy):
    name = "fifo"

    def score(self, observation, action, features):
        return (-features["waiting_age_seconds"], -features["unload"]), {}


class SPTPolicy(ScoredPolicy):
    name = "spt"

    def score(self, observation, action, features):
        return (-features["unload"], features["next_process_seconds"],
                -features["waiting_age_seconds"]), {}


class ECTPolicy(ScoredPolicy):
    name = "ect"

    def score(self, observation, action, features):
        return (features["estimated_next_completion_seconds"],
                -features["waiting_age_seconds"], -features["unload"]), {}


@dataclass(frozen=True)
class BottleneckWeights:
    unblock: float = 4.0
    feed: float = 3.0
    starvation: float = 1.0
    age: float = 0.5
    unload: float = 1.0
    transport: float = 1.0


class BottleneckAwarePolicy(ScoredPolicy):
    name = "bottleneck"

    def __init__(self, weights=BottleneckWeights()):
        super().__init__()
        self.weights = weights

    def score(self, observation, action, features):
        workload = loads(observation)
        scale = max(max(workload.values(), default=0.0), 1.0)
        ref = reference_time(observation)
        source = observation.wafers[action.wafer_id]["location"]
        dest = action.destination
        source_load = workload.get(source, 0.0) / scale
        dest_load = workload.get(dest, 0.0) / scale
        age = features["waiting_age_seconds"] / ref
        starvation = observation.chambers[dest]["idle_age_seconds"] / ref if dest in workload else 0.0
        weights = self.weights
        components = {
            "unblock": weights.unblock * features["source_blocked"] * (1 + source_load + min(age, 2)),
            "feed": weights.feed * dest_load,
            "starvation": weights.starvation * dest_load * min(starvation, 2),
            "age": weights.age * min(age, 4),
            "unload": weights.unload * features["unload"],
            "transport": -weights.transport * features["transport_seconds"] / ref,
        }
        score = sum(components.values())
        return (-score, -features["waiting_age_seconds"]), {
            **components, "total": score, "reference_seconds": ref,
            "source_load_fraction": source_load, "destination_load_fraction": dest_load,
        }


@dataclass(frozen=True)
class AdaptiveThresholds:
    blocked_fraction: float = 0.5
    historical_blocking_rate: float = 0.12
    starvation_ratio: float = 0.25
    queue_count: int = 4
    robot_utilization: float = 0.65


class AdaptiveHeuristicPolicy(ScoredPolicy):
    name = "adaptive"

    def __init__(self, thresholds=AdaptiveThresholds()):
        super().__init__()
        self.thresholds = thresholds
        self.active_rule = None

    def select_action(self, observation, legal_actions):
        executable = [action for action in legal_actions if action.kind != "wait"]
        workload = loads(observation)
        dominant = min(workload, key=lambda key: (-workload[key], key))
        blocked = sum(chamber["status"] == "blocked" for chamber in observation.chambers.values())
        fraction = blocked / len(observation.chambers)
        queue = sum(not wafer["completed"] and wafer["status"] == "waiting"
                    for wafer in observation.wafers.values())
        can_feed = any(action.destination == dominant for action in executable)
        starvation = observation.chambers[dominant]["idle_age_seconds"] / reference_time(observation)
        t = self.thresholds
        if blocked and (fraction >= t.blocked_fraction or observation.history["blocking_rate"] >= t.historical_blocking_rate):
            policy = BottleneckAwarePolicy(BottleneckWeights(unblock=8.0))
            trigger = "blocking_pressure"
        elif workload[dominant] > 0 and can_feed and starvation >= t.starvation_ratio:
            policy = BottleneckAwarePolicy(BottleneckWeights(feed=8.0))
            trigger = "bottleneck_starvation"
        elif queue >= t.queue_count:
            if observation.history["robot_utilization"] >= t.robot_utilization:
                policy, trigger = ECTPolicy(), "queue_and_robot_pressure"
            else:
                policy, trigger = SPTPolicy(), "queue_pressure"
        else:
            policy, trigger = FIFOPolicy(), "normal_state"
        action = policy.select_action(observation, legal_actions)
        prior = self.active_rule
        self.active_rule = policy.name
        self.last_decision = {
            **policy.last_decision, "policy": self.name, "trigger": trigger,
            "switched_from": prior, "switched": prior != policy.name,
            "thresholds": asdict(t),
            "weights": asdict(policy.weights) if isinstance(policy, BottleneckAwarePolicy) else None,
            "evidence": {"blocked_fraction": fraction, "history_blocking_rate": observation.history["blocking_rate"],
                         "queue_count": queue, "robot_utilization": observation.history["robot_utilization"],
                         "bottleneck": dominant, "can_feed": can_feed, "starvation_ratio": starvation,
                         "remaining_workload_seconds": workload},
        }
        return action


POLICIES = {"fifo": FIFOPolicy, "spt": SPTPolicy, "ect": ECTPolicy,
            "bottleneck": BottleneckAwarePolicy, "adaptive": AdaptiveHeuristicPolicy}


def make_policy(name: str) -> Policy:
    return POLICIES[name]()
