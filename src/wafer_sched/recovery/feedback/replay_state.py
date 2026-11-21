"""Bound the memory retained by event logs in the feedback solver's two simulator replays."""

from ..short_budget import PreparedIncident, PreparedSuffix, ReplaySimulator


class QualityReplay(ReplaySimulator):
    def _record(self, kind, before, **kwargs):
        super()._record(kind, before, **kwargs)
        row = self.trace[-1]
        # Both quality checkers read only the affected wafer's pre-completion state.
        # The simulator still validates its full live state after each transition.
        del row["state_after"]
        wafer = row["wafer_id"]
        row["state_before"] = (
            {"wafers": {wafer: before["wafers"][wafer]}}
            if kind in {"RobotPickComplete", "RobotPlaceComplete"} else {}
        )


class FeedbackSuffix(PreparedSuffix):
    simulator_type = QualityReplay


class FeedbackIncident(PreparedIncident):
    simulator_type = QualityReplay
    suffix_type = FeedbackSuffix
