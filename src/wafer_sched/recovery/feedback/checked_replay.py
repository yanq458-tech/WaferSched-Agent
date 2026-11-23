"""Replay with local reuse of previously checked wafer histories, scoped to one engine."""

from ...config import seconds
from ...verification import reject, validate_state
from .frontier_replay import FrontierReplay, FrontierSuffix, FrontierIncident


class CheckedReplay(FrontierReplay):
    indexed = False

    def _assert_state(self):
        if not hasattr(self,"_wafer_validation"):
            self._wafer_validation = {}
        tables=(self._wafers,self._chambers) if self.indexed else None
        result = validate_state(self.state,self.config,wafer_cache=self._wafer_validation,config_tables=tables)
        if self.trace and self.state.time < self.trace[-1]["time"]:
            result = reject("clock_regression","Simulation clock regressed behind its event log")
        if not result:
            raise RuntimeError(result.reason)

    def run_until(self, time):
        # Already settled: an observation at this clock changes no device field.
        # Retain the observation index and event log, as in the reference simulator.
        if time == self.state.time and (not self.state.events or self.state.events[0].time > time):
            seconds(time,"observation time")
            self._queue("ObservationBoundary",time)
            was = self.recording
            self.recording = True
            try:
                self._drain_current()
            finally:
                self.recording = was
            return
        super().run_until(time)


class CheckedSuffix(FrontierSuffix):
    simulator_type = CheckedReplay


class CheckedIncident(FrontierIncident):
    simulator_type = CheckedReplay
    suffix_type = CheckedSuffix
