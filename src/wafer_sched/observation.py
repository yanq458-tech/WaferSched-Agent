"""A value-only, immutable online view; audit snapshots are never policy inputs."""

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping

from .simulator import Simulator


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def plain(value):
    """Detach an observation/decision for JSON publication."""
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Observation:
    time: float
    robot: Mapping
    chambers: Mapping
    wafers: Mapping
    history: Mapping
    completed_count: int


class ObservationBuilder:
    """Trusted adapter maintains integrals from settled, already executed events.

    Only this adapter receives the Simulator. No simulator, config object, trace,
    scheduled timestamp, or not-yet-announced wafer is retained by its output.
    """

    def __init__(self):
        self.cursor = 0
        self.previous = None
        self.ready_since = {}
        self.idle_since = {}
        self.blocking = {}
        self.processing = {}
        self.robot_seconds = 0.0

    def build(self, simulator: Simulator) -> Observation:
        if self.cursor > len(simulator.trace):
            raise ValueError("ObservationBuilder belongs to one run")
        for row in simulator.trace[self.cursor:]:
            after = row["state_after"]
            if self.previous is not None:
                dt = row["time"] - self.previous["time"]
                state = self.previous["state_after"]
                for key, chamber in state["chambers"].items():
                    self.blocking[key] = self.blocking.get(key, 0) + dt * (chamber["status"] == "blocked")
                    self.processing[key] = self.processing.get(key, 0) + dt * (chamber["status"] == "processing")
                robot = state["robot"]
                if robot["busy"] and robot["phase"] in {"picking", "moving_empty", "moving_loaded", "placing"}:
                    self.robot_seconds += dt
            for key, wafer in after["wafers"].items():
                if wafer["released"]:
                    if key not in self.ready_since or row["event"] == "WaferReleased" and row["wafer_id"] == key:
                        self.ready_since[key] = row["time"]
                    if row["event"] == "ChamberProcessComplete" and row["wafer_id"] == key:
                        self.ready_since[key] = row["time"]
            for key, chamber in after["chambers"].items():
                idle = chamber["status"] == "idle" and chamber["available"] and chamber["reservation"] is None
                if idle:
                    self.idle_since.setdefault(key, row["time"])
                else:
                    self.idle_since.pop(key, None)
            self.previous = row
        self.cursor = len(simulator.trace)
        state, configuration = simulator.state, simulator.config
        robot = {
            "position": state.robot.position, "busy": state.robot.busy,
            "carrying": state.robot.carrying, "phase": state.robot.phase,
            "pick_seconds": configuration.robot.pick_seconds,
            "place_seconds": configuration.robot.place_seconds,
            "move_seconds": configuration.robot.move_seconds,
            "travel_times": configuration.robot.travel_times,
        }
        chambers = {}
        for item in configuration.chambers:
            current = state.chambers[item.chamber_id]
            chambers[item.chamber_id] = {
                "wafer_id": current.wafer_id, "status": current.status,
                "available": current.available, "reservation": current.reservation,
                "remaining_seconds": current.remaining,
                "processing_times": dict(item.processing_times),
                "idle_age_seconds": state.time - self.idle_since.get(item.chamber_id, state.time),
            }
        wafers = {}
        for item in configuration.wafers:
            current = state.wafers[item.wafer_id]
            if not current.released:
                continue
            wafers[item.wafer_id] = {
                "location": current.location, "stage": current.stage, "status": current.status,
                "completed": current.completed_at is not None,
                "task_ready_since": self.ready_since[item.wafer_id],
                "route": [{"recipe": step.recipe, "chambers": step.chambers} for step in item.route],
            }
        history = {
            "chamber_blocking_seconds": {key: self.blocking.get(key, 0) for key in chambers},
            "chamber_processing_seconds": {key: self.processing.get(key, 0) for key in chambers},
            "blocking_rate": sum(self.blocking.values()) / (len(chambers) * state.time) if state.time else 0,
            "robot_utilization": self.robot_seconds / state.time if state.time else 0,
        }
        return Observation(state.time, freeze(robot), freeze(chambers), freeze(wafers),
                           freeze(history), sum(w.completed_at is not None for w in state.wafers.values()))
