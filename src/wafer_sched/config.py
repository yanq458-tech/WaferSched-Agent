"""Validated JSON equipment configuration. All durations are finite seconds."""

from dataclasses import dataclass
import json
import math
from pathlib import Path

PORTS = ("LOAD", "OUT")


def seconds(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number of seconds")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    return float(value)


def identifier(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty identifier")
    return value


@dataclass(frozen=True)
class RobotConfig:
    pick_seconds: float
    move_seconds: float
    place_seconds: float
    capacity: int = 1
    initial_position: str = "LOAD"
    travel_times: tuple[tuple[str, str, float], ...] = ()

    def travel(self, source: str, destination: str) -> float:
        if source == destination:
            return 0.0
        return next((duration for left, right, duration in self.travel_times
                     if left == source and right == destination), self.move_seconds)


@dataclass(frozen=True)
class ChamberConfig:
    chamber_id: str
    processing_times: tuple[tuple[str, float], ...]
    capacity: int = 1

    def processing_time(self, recipe: str) -> float:
        return dict(self.processing_times)[recipe]


@dataclass(frozen=True)
class RouteStep:
    recipe: str
    chambers: tuple[str, ...]


@dataclass(frozen=True)
class WaferConfig:
    wafer_id: str
    route: tuple[RouteStep, ...]
    release_seconds: float = 0.0


@dataclass(frozen=True)
class Downtime:
    chamber_id: str
    start: float
    end: float


@dataclass(frozen=True)
class EquipmentConfig:
    robot: RobotConfig
    chambers: tuple[ChamberConfig, ...]
    wafers: tuple[WaferConfig, ...]
    downtimes: tuple[Downtime, ...] = ()
    name: str = "wafer-equipment"

    def __post_init__(self):
        if type(self.robot.capacity) is not int or self.robot.capacity != 1:
            raise ValueError("This model requires robot capacity = 1")
        for label in ("pick_seconds", "move_seconds", "place_seconds"):
            seconds(getattr(self.robot, label), label)
        if not self.chambers or not self.wafers:
            raise ValueError("At least one chamber and one wafer are required")
        ids = [identifier(item.chamber_id, "chamber_id") for item in self.chambers]
        if len(set(ids)) != len(ids) or set(ids) & {*PORTS, "ROBOT"}:
            raise ValueError("Chamber ids must be unique and not reserved")
        wafer_ids = [identifier(item.wafer_id, "wafer_id") for item in self.wafers]
        if len(set(wafer_ids)) != len(wafer_ids):
            raise ValueError("Wafer ids must be unique")
        chambers = {item.chamber_id: item for item in self.chambers}
        for chamber in self.chambers:
            if type(chamber.capacity) is not int or chamber.capacity != 1:
                raise ValueError("This no-buffer model requires chamber capacity = 1")
            recipes = [identifier(recipe, "recipe") for recipe, _ in chamber.processing_times]
            if not recipes or len(set(recipes)) != len(recipes):
                raise ValueError("Processing recipes must be nonempty and unique")
            for recipe, duration in chamber.processing_times:
                seconds(duration, recipe)
        locations = set(ids) | set(PORTS)
        if self.robot.initial_position not in locations:
            raise ValueError("Unknown initial robot position")
        pairs = set()
        for source, destination, duration in self.robot.travel_times:
            if source not in locations or destination not in locations:
                raise ValueError("Travel time refers to an unknown location")
            if (source, destination) in pairs:
                raise ValueError("Duplicate travel-time pair")
            pairs.add((source, destination))
            seconds(duration, "travel time")
            if source == destination and duration != 0:
                raise ValueError("Same-location travel time must be zero")
        for wafer in self.wafers:
            seconds(wafer.release_seconds, "release_seconds")
            if not wafer.route:
                raise ValueError("Each wafer needs a nonempty process route")
            for step in wafer.route:
                identifier(step.recipe, "route recipe")
                if not step.chambers or len(set(step.chambers)) != len(step.chambers):
                    raise ValueError("A route step needs unique eligible chambers")
                for target in step.chambers:
                    if target not in chambers:
                        raise ValueError(f"Unknown route chamber: {target}")
                    if step.recipe not in dict(chambers[target].processing_times):
                        raise ValueError(f"Chamber {target} does not support {step.recipe}")
        previous = {}
        for downtime in sorted(self.downtimes, key=lambda item: (item.chamber_id, item.start)):
            if downtime.chamber_id not in chambers:
                raise ValueError("Downtime refers to an unknown chamber")
            seconds(downtime.start, "downtime start")
            seconds(downtime.end, "downtime end")
            if downtime.end <= downtime.start:
                raise ValueError("Downtime end must follow its start")
            if downtime.start < previous.get(downtime.chamber_id, -1):
                raise ValueError("Downtimes of one chamber must not overlap")
            previous[downtime.chamber_id] = downtime.end

    @classmethod
    def from_dict(cls, data: dict) -> "EquipmentConfig":
        if set(data) - {"robot", "chambers", "wafers", "downtimes", "name"}:
            raise ValueError("Unknown equipment configuration fields")
        for chamber in data["chambers"]:
            if set(chamber) - {"id", "capacity", "processing_times"}:
                raise ValueError("Unknown chamber configuration fields")
        for wafer in data["wafers"]:
            if set(wafer) - {"id", "route", "release_seconds"}:
                raise ValueError("Unknown wafer configuration fields")
            for step in wafer["route"]:
                if set(step) != {"recipe", "chambers"}:
                    raise ValueError("Route steps require exactly recipe and chambers")
        for item in data.get("downtimes", ()):
            if set(item) != {"chamber", "start", "end"}:
                raise ValueError("Downtimes require exactly chamber, start, and end")
        robot = dict(data["robot"])
        robot["travel_times"] = tuple(
            (entry["source"], entry["destination"], entry["seconds"])
            for entry in robot.get("travel_times", ())
        )
        return cls(
            robot=RobotConfig(**robot),
            chambers=tuple(ChamberConfig(
                item["id"], tuple(item["processing_times"].items()), item.get("capacity", 1)
            ) for item in data["chambers"]),
            wafers=tuple(WaferConfig(
                item["id"], tuple(RouteStep(step["recipe"], tuple(step["chambers"]))
                                  for step in item["route"]), item.get("release_seconds", 0)
            ) for item in data["wafers"]),
            downtimes=tuple(Downtime(item["chamber"], item["start"], item["end"])
                            for item in data.get("downtimes", ())),
            name=data.get("name", "wafer-equipment"),
        )

    def to_dict(self) -> dict:
        """Canonical JSON schema, loadable by from_dict without losing timing data."""
        return {
            "name": self.name,
            "robot": {"capacity": self.robot.capacity, "initial_position": self.robot.initial_position,
                      "pick_seconds": self.robot.pick_seconds, "move_seconds": self.robot.move_seconds,
                      "place_seconds": self.robot.place_seconds,
                      "travel_times": [{"source": left, "destination": right, "seconds": duration}
                                       for left, right, duration in self.robot.travel_times]},
            "chambers": [{"id": item.chamber_id, "capacity": item.capacity,
                          "processing_times": dict(item.processing_times)} for item in self.chambers],
            "wafers": [{"id": item.wafer_id, "release_seconds": item.release_seconds,
                        "route": [{"recipe": step.recipe, "chambers": list(step.chambers)}
                                  for step in item.route]} for item in self.wafers],
            "downtimes": [{"chamber": item.chamber_id, "start": item.start, "end": item.end}
                          for item in self.downtimes],
        }


def load_config(path: str | Path) -> EquipmentConfig:
    from .infrastructure.paths import resolve_path
    return EquipmentConfig.from_dict(json.loads(resolve_path(path).read_text(encoding="utf-8")))
