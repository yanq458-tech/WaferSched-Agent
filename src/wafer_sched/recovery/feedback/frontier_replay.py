"""Compact transient event-log snapshots; the original engine executes every action and check."""

from .replay_state import FeedbackIncident, FeedbackSuffix, QualityReplay


class FrontierReplay(QualityReplay):
    recording = False

    def submit(self, action):
        was = self.recording
        self.recording = True
        try:
            return super().submit(action)
        finally:
            self.recording = was

    def advance_next(self):
        was = self.recording
        self.recording = True
        try:
            return super().advance_next()
        finally:
            self.recording = was

    def snapshot(self):
        if not self.recording:
            return super().snapshot()
        # The only consumed before-state payload is for the wafer on a PickComplete
        # or PlaceComplete event. Capture the next event before it is popped.
        event = self.state.events[0] if self.state.events else None
        if event and event.kind in ("RobotPickComplete","RobotPlaceComplete"):
            w = self.state.wafers[event.wafer_id]
            return {"wafers": {event.wafer_id: {"stage":w.stage,
                         "processing_records":[v.copy() for v in w.processing_records]}}}
        return {"wafers": {}}


class FrontierSuffix(FeedbackSuffix):
    simulator_type = FrontierReplay


class FrontierIncident(FeedbackIncident):
    simulator_type = FrontierReplay
    suffix_type = FrontierSuffix
