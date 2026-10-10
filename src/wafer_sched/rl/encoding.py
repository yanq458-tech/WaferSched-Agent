"""Stable value-only slot encodings. No configuration, simulator or event access."""

from dataclasses import dataclass
import math

import numpy as np

from ..actions import Action

ROBOT_PHASES = ("idle", "scheduled", "picking", "moving_empty", "moving_loaded",
                "placing", "waiting_recovery")
CHAMBER_STATES = ("idle", "processing", "paused", "blocked", "queued")
WAFER_STATES = ("waiting", "processing", "paused", "picking", "transporting",
                "placing", "completed", "not_released", "queued", "unloading_complete")


@dataclass(frozen=True)
class EncodingSchema:
    max_wafers: int = 8
    max_chambers: int = 4
    max_stages: int = 3
    time_scale_seconds: float = 100.0
    version: int = 1

    def __post_init__(self):
        for key in ("max_wafers", "max_chambers", "max_stages"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        if (isinstance(self.time_scale_seconds, bool)
                or not math.isfinite(self.time_scale_seconds) or self.time_scale_seconds <= 0):
            raise ValueError("time_scale_seconds must be finite and positive")
        if self.version != 1:
            raise ValueError("Unsupported encoding schema version")

    @property
    def action_count(self):
        return 1 + self.max_wafers * (self.max_chambers + 1)

    @property
    def observation_size(self):
        n, c, k = self.max_wafers, self.max_chambers, self.max_stages
        positions = c + 3  # LOAD, OUT, chamber slots, ROBOT
        robot = (positions + 1 + 2 * (n + 1) + len(ROBOT_PHASES)
                 + 2 * (positions + 1) + 2 + 3 + (c + 2) ** 2)
        chamber = 2 + len(CHAMBER_STATES) + 2 * (n + 1) + 4
        wafer = 5 + len(WAFER_STATES) + positions + 1 + k * 2 * c
        return 6 + robot + c * chamber + n * wafer


def _onehot(index, size):
    if not 0 <= index < size:
        raise ValueError("Unencodable slot")
    return [float(i == index) for i in range(size)]


class ObservationEncoder:
    def __init__(self, schema=EncodingSchema()):
        self.schema = schema

    def encode(self, observation):
        """Full remaining route/processing matrix is essential to Markov sufficiency."""
        schema = self.schema
        n, c, k = schema.max_wafers, schema.max_chambers, schema.max_stages
        wafers, chambers = sorted(observation.wafers), sorted(observation.chambers)
        if len(wafers) > n or len(chambers) > c:
            raise ValueError("Scenario exceeds the declared slot capacity; no truncation allowed")
        if any(len(w["route"]) > k for w in observation.wafers.values()):
            raise ValueError("Route exceeds max_stages")
        wi, ci = {key: i for i, key in enumerate(wafers)}, {key: i for i, key in enumerate(chambers)}
        positions = {"LOAD": 0, "OUT": 1, **{key: i + 2 for key, i in ci.items()}, "ROBOT": c + 2}

        def time(value):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Observable durations must be nonnegative and finite")
            return value / (value + schema.time_scale_seconds)

        def position(value, allow_none=False):
            return _onehot(c + 3 if value is None and allow_none else positions[value],
                           c + 3 + int(allow_none))

        def wafer_slot(value):
            return _onehot(n if value is None else wi[value], n + 1)

        history, robot = observation.history, observation.robot
        data = [time(observation.time), observation.completed_count / n, len(wafers) / n,
                len(chambers) / c, history["blocking_rate"], history["robot_utilization"]]
        data += position(robot["position"]) + [float(robot["busy"])]
        data += wafer_slot(robot["carrying"]) + wafer_slot(robot.get("active_wafer"))
        data += _onehot(ROBOT_PHASES.index(robot["phase"]), len(ROBOT_PHASES))
        data += position(robot.get("source"), True) + position(robot.get("destination"), True)
        data += [time(robot.get("remaining_action_seconds", 0)), float(robot.get("high_level", False))]
        data += [time(robot[key]) for key in ("pick_seconds", "place_seconds", "move_seconds")]
        locations = ["LOAD", "OUT", *chambers]
        explicit = {(left, right): value for left, right, value in robot["travel_times"]}
        for i in range(c + 2):
            for j in range(c + 2):
                duration = 0.0 if i == j or i >= len(locations) or j >= len(locations) else explicit.get(
                    (locations[i], locations[j]), robot["move_seconds"])
                data.append(time(duration))
        ch_size = 2 + len(CHAMBER_STATES) + 2 * (n + 1) + 4
        for i in range(c):
            if i >= len(chambers):
                data += [0.0] * ch_size
                continue
            key = chambers[i]
            ch = observation.chambers[key]
            data += [1.0, float(ch["available"])]
            data += _onehot(CHAMBER_STATES.index(ch["status"]), len(CHAMBER_STATES))
            data += wafer_slot(ch["wafer_id"]) + wafer_slot(ch["reservation"])
            data += [time(ch["remaining_seconds"]), time(ch["idle_age_seconds"]),
                     time(history["chamber_blocking_seconds"][key]),
                     time(history["chamber_processing_seconds"][key])]
        wf_size = 5 + len(WAFER_STATES) + c + 3 + 1 + k * 2 * c
        for i in range(n):
            if i >= len(wafers):
                data += [0.0] * wf_size
                continue
            w = observation.wafers[wafers[i]]
            data += [1.0, float(w["completed"]), float(w["status"] == "waiting"),
                     w["stage"] / k, len(w["route"]) / k]
            data += _onehot(WAFER_STATES.index(w["status"]), len(WAFER_STATES))
            data += position(w["location"]) + [time(observation.time - w["task_ready_since"])]
            for stage in range(k):
                step = w["route"][stage] if stage < len(w["route"]) else None
                for ch in range(c):
                    compatible = step is not None and ch < len(chambers) and chambers[ch] in step["chambers"]
                    duration = observation.chambers[chambers[ch]]["processing_times"][step["recipe"]] if compatible else 0
                    data += [float(compatible), time(duration)]
        result = np.asarray(data, dtype=np.float32)
        if result.shape != (schema.observation_size,) or not np.isfinite(result).all():
            raise ValueError("Invalid observation encoding")
        if (result < 0).any() or (result > 1).any():
            raise ValueError("Observation lies outside its normalized space")
        return result


class ActionEncoder:
    def __init__(self, schema=EncodingSchema()):
        self.schema = schema

    def index(self, action, observation):
        if action == Action.wait():
            return 0
        if action.kind not in {"transfer", "unload"} or action.source is not None:
            raise ValueError("Only original catalogue macro transfers/unloads/wait are supported")
        wafers, chambers = sorted(observation.wafers), sorted(observation.chambers)
        if len(wafers) > self.schema.max_wafers or len(chambers) > self.schema.max_chambers:
            raise ValueError("Slot capacity exceeded")
        w = wafers.index(action.wafer_id)
        if action.kind == "unload":
            if action.destination != "OUT":
                raise ValueError("Unload must target OUT")
            d = self.schema.max_chambers
        else:
            d = chambers.index(action.destination)
        return 1 + w * (self.schema.max_chambers + 1) + d

    def catalogue(self, observation, legal_actions):
        table = {self.index(action, observation): action for action in legal_actions}
        if len(table) != len(legal_actions):
            raise ValueError("Action encoding collision")
        return table

    def mask(self, observation, legal_actions):
        result = np.zeros(self.schema.action_count, dtype=bool)
        for index in self.catalogue(observation, legal_actions):
            result[index] = True
        return result

    def decode(self, index, observation, legal_actions):
        if isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer)):
            raise ValueError("Action index must be an integer")
        table = self.catalogue(observation, legal_actions)
        if int(index) not in table:
            raise ValueError(f"Illegal or masked action index: {index}")
        return table[int(index)]
