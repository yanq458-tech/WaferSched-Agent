"""Replay a measured fault and contract its forced prefix into a v1.2 suffix."""

from copy import deepcopy
from dataclasses import dataclass, replace
from fractions import Fraction
from math import lcm

from ..actions import Action
from ..config import EquipmentConfig, seconds
from ..cpsat_model import UnsupportedModel
from ..simulator import Simulator
from .state import RecoveryProblem


def delta(a, b):
    return float(Fraction(str(a)) - Fraction(str(b)))


class BrokenDeadline(Exception):
    """An irrevocable physical event already missed a quality deadline."""


class Suffix(RecoveryProblem):
    clock_scale = 1

    def allows_occupied(self):
        return self.snapshot["chambers"][self.failed_chamber]["status"] == "blocked"

    @property
    def scale(self):
        value = lcm(super().scale, self.clock_scale)
        if value > 10000:
            raise UnsupportedModel("Exact clock exceeds 10000 ticks/s")
        return value


def checks(trace, residence, holding):
    picked = {}
    for e in trace:
        wid = e["wafer_id"]
        if e["event"] == "RobotPickComplete":
            picked[wid] = e["time"]
            if e["source"] != "LOAD":
                w = e["state_before"]["wafers"][wid]
                i = w["stage"] - 1
                limit = residence[wid][i]
                if (
                    limit is not None
                    and delta(e["time"], w["processing_records"][i]["end"]) > limit
                ):
                    raise BrokenDeadline(f"{wid} missed residency at {e['time']}")
        elif e["event"] == "RobotPlaceComplete":
            limit = holding[wid][e["state_before"]["wafers"][wid]["stage"]]
            if limit is not None and delta(e["time"], picked[wid]) > limit:
                raise BrokenDeadline(f"{wid} missed holding limit at {e['time']}")
    return picked


@dataclass
class Continuation:
    config: EquipmentConfig
    actions: list
    snapshot: dict
    failed_chamber: str
    residency: dict
    holding: dict
    policy: str = "empty_only"
    dispatch_lag: float = 0

    @classmethod
    def capture(cls, sim, failed_chamber, residency, holding=None, **kw):
        actions = [
            {"time": e["time"], "action": deepcopy(e["details"]["action"])}
            for e in sim.trace
            if e["event"] == "ActionAccepted"
        ]
        if holding is None:
            holding = {w.wafer_id: [None] * (len(w.route) + 1) for w in sim.config.wafers}
        return cls(sim.config, actions, sim.snapshot(), failed_chamber, residency, holding, **kw)

    def to_dict(self):
        return deepcopy({**vars(self), "config": self.config.to_dict(), "schema_version": 2})

    @classmethod
    def from_dict(cls, raw):
        fields = deepcopy(raw)
        if fields.pop("schema_version") != 2:
            raise ValueError("Expected continuation schema 2")
        fields["config"] = EquipmentConfig.from_dict(fields["config"])
        return cls(**fields)

    def at_fault(self):
        if min(self.config.robot.pick_seconds, self.config.robot.place_seconds) <= 0:
            raise UnsupportedModel("Positive pick and place durations required")
        if self.config.downtimes:
            raise UnsupportedModel("One fault, fault-free prehistory required")
        seconds(self.dispatch_lag, "dispatch lag")
        for mapping, extra in ((self.residency, 0), (self.holding, 1)):
            if set(mapping) != {w.wafer_id for w in self.config.wafers}:
                raise ValueError("Quality limits must name every wafer")
            for w in self.config.wafers:
                if len(mapping[w.wafer_id]) != len(w.route) + extra:
                    raise ValueError("Wrong number of limits")
                for v in mapping[w.wafer_id]:
                    if v is not None:
                        seconds(v, "quality limit")
        sim = Simulator(self.config)
        if self.failed_chamber not in sim.state.chambers:
            raise ValueError("Unknown failed chamber")
        for entry in self.actions:
            if entry["time"] != sim.state.time:
                sim.run_until(entry["time"])
            if not sim.submit(Action(**entry["action"])):
                raise ValueError("Illegal historical action")
        sim.run_until(self.snapshot["time"])

        # ObservationBoundary events consume sequence IDs. Physical order among
        # pending simultaneous events is preserved by snapshot sorting.
        def physical(snapshot):
            out = deepcopy(snapshot)
            for event in out["events"]:
                event.pop("sequence")
            return out

        if physical(sim.snapshot()) != physical(self.snapshot):
            raise ValueError("Snapshot disagrees with replay of submitted actions")
        failed = sim.state.chambers[self.failed_chamber]
        if self.policy not in {"empty_only", "evacuate_finished", "sealed_finished"}:
            raise UnsupportedModel("Unqualified chamber quality policy")
        if failed.wafer_id and not (
            self.policy in {"evacuate_finished", "sealed_finished"} and failed.status == "blocked"
        ):
            raise UnsupportedModel(
                "Occupied fault requires a qualified finished-wafer evacuation policy"
            )
        if any(w.location == "LOAD" and w.completed_at is None for w in sim.state.wafers.values()):
            raise UnsupportedModel("No new admissions: supply only WIP already in the tool")
        if sim.state.robot.busy and sim.state.robot.high_level:
            raise UnsupportedModel("Mid-macro command requires an explicit commitment contract")
        if failed.reservation:
            raise UnsupportedModel(
                "Interrupted placement into failed chamber requires quality policy"
            )
        if (
            self.policy == "sealed_finished"
            and sim.state.robot.phase == "picking"
            and sim.state.robot.source == self.failed_chamber
        ):
            raise UnsupportedModel(
                "Sealing during a committed extraction requires a process policy"
            )
        if sim.completed:
            raise UnsupportedModel("Fault snapshot has no unfinished WIP")
        return sim

    def prepare(self):
        sim = self.at_fault()
        start = sim.state.time
        before = len(sim.trace)
        sim.state.chambers[self.failed_chamber].available = False
        free = sim.state.robot.phase_end if sim.state.robot.busy else start
        dispatch = max(free, float(Fraction(str(start)) + Fraction(str(self.dispatch_lag))))
        sim.run_until(dispatch)
        picked = checks(sim.trace, self.residency, self.holding)
        prefix = {
            "fault_time": start,
            "dispatch_time": dispatch,
            "offset": delta(dispatch, start),
            "policy": self.policy,
            "committed_robot": self.snapshot["robot"],
            "events": sim.trace[before:],
        }
        unfinished = tuple(
            w for w in self.config.wafers if sim.state.wafers[w.wafer_id].completed_at is None
        )
        if not unfinished:
            prefix["completion_delay"] = delta(
                max(w.completed_at for w in sim.state.wafers.values()), start
            )
            return None, prefix
        snap = sim.snapshot()
        for wid in snap["completed_wafers"]:
            del snap["wafers"][wid]
        snap["completed_wafers"] = []
        if sim.state.robot.carrying:
            snap["carrying_since"] = picked[sim.state.robot.carrying]
        suffix = Suffix(
            replace(self.config, wafers=unfinished),
            snap,
            self.failed_chamber,
            {w.wafer_id: self.residency[w.wafer_id] for w in unfinished},
            {w.wafer_id: self.holding[w.wafer_id] for w in unfinished},
        )
        suffix.clock_scale = Fraction(str(prefix["offset"])).denominator
        suffix.sealed_finished = self.policy == "sealed_finished"
        suffix.scale
        return suffix, prefix
