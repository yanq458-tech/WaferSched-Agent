"""Validate and restore real Simulator states without changing the original engine."""

from copy import deepcopy
from dataclasses import dataclass, fields
from fractions import Fraction
import heapq
import math

from ..config import EquipmentConfig, Downtime, seconds
from ..cpsat_model import UnsupportedModel, ticks, time_scale
from ..equipment import EquipmentState, RobotState, ChamberState, WaferState
from ..events import Event
from ..simulator import Simulator


def _restore(cls, data):
    names = {f.name for f in fields(cls)}
    return cls(**{k: deepcopy(v) for k, v in data.items() if k in names})


@dataclass
class RecoveryProblem:
    config: EquipmentConfig
    snapshot: dict
    failed_chamber: str
    residency: dict
    holding: dict | None = None
    allowed_actions: tuple = ("pick", "move", "place", "wait")

    def __post_init__(self):
        self.snapshot = deepcopy(self.snapshot)
        self.residency = deepcopy(self.residency)
        self.holding = deepcopy(self.holding or {
            w.wafer_id: [None] * (len(w.route) + 1) for w in self.config.wafers})
        if self.config.downtimes:
            raise UnsupportedModel("Pass a fault-free configuration; the recovery fault is separate")
        if set(self.allowed_actions) != {"pick", "move", "place", "wait"}:
            raise UnsupportedModel("V1 requires the full primitive action set plus explicit waiting")
        if self.failed_chamber not in {c.chamber_id for c in self.config.chambers}:
            raise ValueError("Unknown failed chamber")
        sim = self.simulator(0)
        validation = sim.validate_state()
        if not validation:
            raise ValueError(validation.reason)
        s = sim.state
        if s.robot.busy or s.robot.phase != "idle":
            raise UnsupportedModel("Capture at a robot action boundary, including idle carrying")
        if any(c.reservation for c in s.chambers.values()):
            raise UnsupportedModel("Outstanding reservations are unsupported")
        if s.chambers[self.failed_chamber].wafer_id is not None:
            raise UnsupportedModel("V1 requires the failed chamber to be empty")
        if any(c.status not in {"idle", "processing", "blocked"} for c in s.chambers.values()):
            raise UnsupportedModel("Paused/queued processes are unsupported")
        if any(not c.available for k, c in s.chambers.items() if k != self.failed_chamber):
            raise UnsupportedModel("Only one failed chamber is supported")
        if any(not w.released or w.completed_at is not None for w in s.wafers.values()):
            raise UnsupportedModel("Input must contain only released, effective, unfinished WIP")
        if any(e.kind != "ChamberProcessComplete" for e in s.events):
            raise UnsupportedModel("Only remaining healthy process completions may be pending")
        if any(e.source not in s.chambers for e in s.events):
            raise ValueError("Pending event has an unknown source")
        for key, c in s.chambers.items():
            events = [e for e in s.events if e.source == key]
            if c.status == "processing":
                if (len(events) != 1 or events[0].time != c.ready_at
                        or events[0].wafer_id != c.wafer_id
                        or c.ready_at <= s.time or c.process_started_at is None):
                    raise ValueError("Inconsistent pending process completion")
                w = s.wafers[c.wafer_id]
                spec = sim._wafers[c.wafer_id]
                duration = sim._chambers[key].processing_time(spec.route[w.stage].recipe)
                if not math.isclose(c.ready_at - c.process_started_at, duration, abs_tol=1e-9):
                    raise UnsupportedModel("Interrupted or inconsistent initial processing")
            elif events:
                raise ValueError("Unexpected process event for an inactive chamber")
        ids = set(s.wafers)
        if set(self.residency) != ids or set(self.holding) != ids:
            raise ValueError("Residency/holding must cover exactly the WIP IDs")
        for w in self.config.wafers:
            for mapping, count in ((self.residency, len(w.route)), (self.holding, len(w.route)+1)):
                if len(mapping[w.wafer_id]) != count:
                    raise ValueError("One residency per process and one holding bound per transfer required")
                for limit in mapping[w.wafer_id]:
                    if limit is not None:
                        seconds(limit, "time limit")
        if s.robot.carrying:
            # Pick completion time is not stored in RobotState. Require it explicitly.
            picked = self.snapshot.get("carrying_since")
            seconds(picked, "carrying_since")
            if picked > s.time:
                raise ValueError("carrying_since is in the future")
        # Reject nonmetric movement: otherwise intermediate moves can beat direct travel.
        locations = ["LOAD", "OUT", *s.chambers]
        for a in locations:
            for b in locations:
                for c in locations:
                    if (Fraction(str(self.config.robot.travel(a, c))) >
                            Fraction(str(self.config.robot.travel(a, b))) +
                            Fraction(str(self.config.robot.travel(b, c)))):
                        raise UnsupportedModel("V1 requires directed triangle-inequality travel times")
        self.scale  # validate exact representability now

    @property
    def now(self):
        return self.snapshot["time"]

    @property
    def scale(self):
        values = [self.now]
        for c in self.snapshot["chambers"].values():
            values += [c[k] for k in ("ready_at", "process_started_at") if c.get(k) is not None]
        for w in self.snapshot["wafers"].values():
            values += [r["end"] for r in w["processing_records"]]
        if self.snapshot.get("carrying_since") is not None:
            values.append(self.snapshot["carrying_since"])
        values += [x for mapping in (self.residency, self.holding)
                   for row in mapping.values() for x in row if x is not None]
        scale = math.lcm(time_scale(self.config), *(Fraction(str(x)).denominator for x in values))
        if scale > 10000:
            raise UnsupportedModel("Warm-state times need >10000 ticks/second; no rounding allowed")
        return scale

    def relative_tick(self, absolute):
        return ticks(absolute, self.scale) - ticks(self.now, self.scale)

    def simulator(self, repair_delay):
        """Detached engine restored with original events, records and fault recovery event."""
        seconds(repair_delay, "repair_delay")
        from dataclasses import replace
        config = self.config
        if repair_delay > 0:
            config = replace(config, downtimes=(Downtime(
                self.failed_chamber, self.now, self.now + repair_delay),))
        sim = Simulator.__new__(Simulator)
        sim.config, sim.seed, sim.trace = config, 0, []
        sim._wafers = {w.wafer_id: w for w in config.wafers}
        sim._chambers = {c.chamber_id: c for c in config.chambers}
        raw = self.snapshot
        sim.state = EquipmentState(
            raw["time"], _restore(RobotState, raw["robot"]),
            {k: _restore(ChamberState, v) for k, v in raw["chambers"].items()},
            {k: _restore(WaferState, v) for k, v in raw["wafers"].items()},
            [_restore(Event, e) for e in raw["events"]])
        heapq.heapify(sim.state.events)
        sim._sequence = max((e.sequence for e in sim.state.events), default=0)
        sim.state.chambers[self.failed_chamber].available = repair_delay == 0
        if repair_delay > 0:
            sim._queue("ChamberAvailable", self.now + repair_delay, source=self.failed_chamber)
        return sim

    def to_dict(self):
        return {"schema_version": 1, "config": self.config.to_dict(), "snapshot": self.snapshot,
                "failed_chamber": self.failed_chamber, "residency": self.residency,
                "holding": self.holding, "allowed_actions": list(self.allowed_actions)}

    @classmethod
    def from_dict(cls, data):
        if data.get("schema_version") != 1:
            raise ValueError("Expected recovery schema_version=1")
        expected = {"schema_version", "config", "snapshot", "failed_chamber", "residency",
                    "holding", "allowed_actions"}
        if set(data) - expected:
            raise ValueError("Unknown recovery input fields")
        return cls(EquipmentConfig.from_dict(data["config"]), data["snapshot"],
                   data["failed_chamber"], data["residency"], data.get("holding"),
                   tuple(data.get("allowed_actions", ("pick", "move", "place", "wait"))))
