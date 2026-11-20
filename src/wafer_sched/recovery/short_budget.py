"""Per-query preparation and detached simulator observations for short-budget recovery."""

from copy import copy, deepcopy
from fractions import Fraction
from functools import cached_property
from math import lcm

from ..cpsat_model import UnsupportedModel
from ..simulator import Simulator
from .continuation import Continuation, Suffix
from .state import RecoveryProblem


class ReplaySimulator(Simulator):
    """Identical engine, including validation; specialize serialization of primitive records."""

    def snapshot(self):
        s = self.state
        wafers = {}
        for key, wafer in s.wafers.items():
            obs = vars(wafer).copy()
            # The simulator writes flat, scalar-valued processing and transfer records.
            obs["processing_records"] = [v.copy() for v in wafer.processing_records]
            obs["transfer_records"] = [v.copy() for v in wafer.transfer_records]
            wafers[key] = obs
        robot = vars(s.robot).copy()
        robot["remaining_action_seconds"] = (
            max(0.0, s.robot.phase_end - s.time) if s.robot.phase_end is not None else 0.0
        )
        return dict(
            time=s.time,
            robot=robot,
            wafers=wafers,
            chambers={k: vars(v).copy() for k, v in s.chambers.items()},
            events=[vars(v).copy() for v in sorted(s.events)],
            deadlock=deepcopy(s.deadlock),
            waiting_queue=[k for k, v in s.wafers.items() if v.released and v.status == "waiting"],
            completed_wafers=[k for k, v in s.wafers.items() if v.completed_at is not None],
        )


class PreparedSuffix(Suffix):
    simulator_type = ReplaySimulator

    @cached_property
    def input_scale(self):
        return RecoveryProblem.scale.fget(self)

    @property
    def scale(self):
        value = lcm(self.input_scale, self.clock_scale)
        if value > 10000:
            raise UnsupportedModel("Exact clock exceeds 10000 ticks/s")
        return value

    def check_travel(self, state):
        locations = ["LOAD", "OUT", *state.chambers]
        matrix = [
            [Fraction(str(self.config.robot.travel(a, b))) for b in locations] for a in locations
        ]
        # The common denominator gives the same exact triangle test with integer additions.
        denominator = lcm(*(v.denominator for row in matrix for v in row))
        table = [[int(v * denominator) for v in row] for row in matrix]
        for row in table:
            for b, ab in enumerate(row):
                if any(ac > ab + bc for ac, bc in zip(row, table[b])):
                    raise UnsupportedModel("V1 requires directed triangle-inequality travel times")


class PreparedIncident(Continuation):
    simulator_type = ReplaySimulator
    suffix_type = PreparedSuffix

    @cached_property
    def prepared(self):
        return super().prepare()

    def prepare(self):
        # A fixed-delay query may refine its own clock_scale; share only read-only input fields.
        suffix, prefix = self.prepared
        return copy(suffix), prefix.copy()
