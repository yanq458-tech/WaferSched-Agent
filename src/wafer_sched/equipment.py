"""Explicit mutable physical state; public observations are detached snapshots."""

from dataclasses import asdict, dataclass, field

from .events import Event


@dataclass
class RobotState:
    position: str
    busy: bool = False
    carrying: str | None = None
    phase: str = "idle"
    active_wafer: str | None = None
    source: str | None = None
    destination: str | None = None
    high_level: bool = False
    phase_end: float | None = None
    place_remaining: float = 0.0
    transfer_start: float | None = None
    transfer_source: str | None = None


@dataclass
class ChamberState:
    wafer_id: str | None = None
    status: str = "idle"
    available: bool = True
    reservation: str | None = None
    remaining: float = 0.0
    ready_at: float | None = None
    process_started_at: float | None = None


@dataclass
class WaferState:
    location: str = "LOAD"
    stage: int = 0
    status: str = "waiting"
    released: bool = True
    completed_at: float | None = None
    processing_records: list[dict] = field(default_factory=list)
    transfer_records: list[dict] = field(default_factory=list)


@dataclass
class EquipmentState:
    time: float
    robot: RobotState
    chambers: dict[str, ChamberState]
    wafers: dict[str, WaferState]
    events: list[Event] = field(default_factory=list)
    deadlock: dict | None = None

    def snapshot(self) -> dict:
        snapshot = asdict(self)
        snapshot["events"] = [asdict(event) for event in sorted(self.events)]
        snapshot["robot"]["remaining_action_seconds"] = (
            max(0.0, self.robot.phase_end - self.time)
            if self.robot.phase_end is not None else 0.0
        )
        snapshot["waiting_queue"] = [key for key, wafer in self.wafers.items()
                                     if wafer.released and wafer.status == "waiting"]
        snapshot["completed_wafers"] = [key for key, wafer in self.wafers.items()
                                        if wafer.completed_at is not None]
        return snapshot
