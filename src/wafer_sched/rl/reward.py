"""Interval rewards reuse the original event-metric physical definitions."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RewardWeights:
    completion: float = 10.0
    waiting: float = 0.5
    blocking: float = 0.1
    robot: float = 0.1
    elapsed: float = 2.0
    deadlock: float = 10.0
    reference_seconds: float = 100.0

    def __post_init__(self):
        for key, value in vars(self).items():
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid reward weight: {key}")
        if self.reference_seconds == 0:
            raise ValueError("reference_seconds must be positive")


class RewardCalculator:
    def __init__(self, weights=RewardWeights()):
        self.weights = weights

    def calculate(self, trace, start_index, *, deadlocked=False):
        """start_index is the preceding settled endpoint, including zero-time rows."""
        rows = trace[start_index:]
        initial = trace[0]["state_after"]
        n, c = len(initial["wafers"]), len(initial["chambers"])
        raw = {"completed_wafers": rows[-1]["completed_count"] - rows[0]["completed_count"],
               "elapsed_seconds": rows[-1]["time"] - rows[0]["time"],
               "waiting_wafer_seconds": 0.0, "blocking_chamber_seconds": 0.0,
               "robot_seconds": 0.0, "deadlock_unfinished_fraction": 0.0}
        for left, right in zip(rows, rows[1:]):
            dt = right["time"] - left["time"]
            if dt < 0 or not math.isfinite(dt):
                raise ValueError("Nonmonotone event reward")
            state, robot = left["state_after"], left["state_after"]["robot"]
            active = robot["busy"] and robot["phase"] in {"picking", "moving_empty", "moving_loaded", "placing"}
            raw["robot_seconds"] += dt * active
            raw["blocking_chamber_seconds"] += dt * sum(ch["status"] == "blocked" for ch in state["chambers"].values())
            for key, wafer in state["wafers"].items():
                transported = (robot["busy"] and robot["phase"] in {"picking", "moving_loaded", "placing"}
                               and robot["active_wafer"] == key)
                if wafer["released"] and wafer["completed_at"] is None and wafer["status"] != "processing" and not transported:
                    raw["waiting_wafer_seconds"] += dt
        if deadlocked:
            raw["deadlock_unfinished_fraction"] = (n - rows[-1]["completed_count"]) / n
        w, ref = self.weights, self.weights.reference_seconds
        terms = {"completion": w.completion * raw["completed_wafers"] / n,
                 "waiting": -w.waiting * raw["waiting_wafer_seconds"] / (n * ref),
                 "blocking": -w.blocking * raw["blocking_chamber_seconds"] / (c * ref),
                 "robot": -w.robot * raw["robot_seconds"] / ref,
                 "elapsed": -w.elapsed * raw["elapsed_seconds"] / ref,
                 "deadlock": -w.deadlock * raw["deadlock_unfinished_fraction"]}
        return float(sum(terms.values())), {"raw": raw, "weighted": terms}
