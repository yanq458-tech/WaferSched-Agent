"""Stable event order: physical completions precede new operation starts."""

from dataclasses import dataclass, field

PRIORITY = {
    "ChamberUnavailable": 0, "ChamberAvailable": 1,
    "ChamberProcessComplete": 2, "WaferReleased": 3,
    "RobotPickComplete": 4, "RobotMoveComplete": 4, "RobotPlaceComplete": 4,
    "RobotPickStart": 5, "RobotMoveStart": 5, "RobotPlaceStart": 5,
    "ChamberProcessStart": 6, "WaferCompleted": 7,
}


@dataclass(order=True, frozen=True)
class Event:
    time: float
    priority: int
    sequence: int
    kind: str = field(compare=False)
    wafer_id: str | None = field(default=None, compare=False)
    source: str | None = field(default=None, compare=False)
    destination: str | None = field(default=None, compare=False)
    phase: str | None = field(default=None, compare=False)
    duration: float = field(default=0.0, compare=False)
    started_at: float | None = field(default=None, compare=False)
