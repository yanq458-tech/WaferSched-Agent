"""Single-gripper, no-buffer event engine; no scheduling optimization here."""

from dataclasses import asdict
import heapq

from .actions import Action
from .config import EquipmentConfig, seconds
from .equipment import ChamberState, EquipmentState, RobotState, WaferState
from .events import Event, PRIORITY
from .verification import ValidationResult, reject, validate_action, validate_state


class Simulator:
    def __init__(self, config: EquipmentConfig, *, seed: int = 0):
        self.config = config
        self.seed = seed  # Metadata only: this deterministic stage consumes no random numbers.
        self._sequence = 0
        self.trace: list[dict] = []
        self.state = EquipmentState(
            0.0, RobotState(config.robot.initial_position),
            {item.chamber_id: ChamberState() for item in config.chambers},
            {item.wafer_id: WaferState(released=item.release_seconds == 0,
                                     status="waiting" if item.release_seconds == 0 else "not_released")
             for item in config.wafers},
        )
        self._wafers = {item.wafer_id: item for item in config.wafers}
        self._chambers = {item.chamber_id: item for item in config.chambers}
        for item in config.wafers:
            if item.release_seconds > 0:
                self._queue("WaferReleased", item.release_seconds, wafer_id=item.wafer_id)
        for downtime in config.downtimes:
            self._queue("ChamberUnavailable", downtime.start, source=downtime.chamber_id)
            self._queue("ChamberAvailable", downtime.end, source=downtime.chamber_id)
        self._record("Initialized", self.state.snapshot())
        self._drain_current()
        self._assert_state()

    @property
    def completed(self) -> bool:
        return all(wafer.completed_at is not None for wafer in self.state.wafers.values())

    def snapshot(self) -> dict:
        return self.state.snapshot()

    def validate_state(self) -> ValidationResult:
        result = validate_state(self.state, self.config)
        if self.trace and self.state.time < self.trace[-1]["time"]:
            return reject("clock_regression", "Simulation clock regressed behind its event log")
        return result

    def validate_action(self, action: Action) -> ValidationResult:
        return validate_action(self.state, self.config, action)

    def submit(self, action: Action) -> ValidationResult:
        """Invalid actions return a reason and leave state, queue, and trace unchanged."""
        self._assert_state()
        result = self.validate_action(action)
        if not result:
            return result
        if action.kind == "wait":
            self.advance_next()
            return result
        before = self.snapshot()
        robot = self.state.robot
        robot.busy = True
        robot.phase = "scheduled"
        robot.high_level = action.kind in {"transfer", "unload"}
        robot.active_wafer = action.wafer_id or robot.carrying
        robot.destination = action.destination
        robot.source = (action.source or self.state.wafers[action.wafer_id].location
                        if action.wafer_id is not None else robot.position)
        if robot.high_level:
            robot.transfer_start = self.state.time
            robot.transfer_source = robot.source
        if action.kind in {"transfer", "unload", "place"}:
            if action.destination in self.state.chambers:
                self.state.chambers[action.destination].reservation = action.wafer_id
        if robot.high_level:
            if robot.position != robot.source:
                self._move(robot.source, "moving_empty")
            else:
                self._pick()
        elif action.kind == "pick":
            self._pick()
        elif action.kind == "move":
            self._move(action.destination, "moving_loaded" if robot.carrying else "moving_empty")
        else:
            self._request_place(self.config.robot.place_seconds)
        self._record("ActionAccepted", before, wafer_id=action.wafer_id,
                     source=robot.source, destination=action.destination,
                     details={"action": asdict(action)})
        self._drain_current()
        self._assert_state()
        return result

    def advance_next(self) -> bool:
        """Advance only to the minimum queued timestamp, settling all simultaneous events."""
        if not self.state.events:
            return False
        self._assert_state()
        target = self.state.events[0].time
        if target < self.state.time:
            raise RuntimeError("Event timestamp regressed; refusing to modify the clock")
        self.state.time = target
        for chamber in self.state.chambers.values():
            if chamber.status == "processing":
                chamber.remaining = max(0.0, chamber.ready_at - target)
        self._drain_current()
        return True

    def run_until(self, time: float) -> None:
        """An explicit observation event closes a window without skipping queued work."""
        seconds(time, "observation time")
        if time < self.state.time:
            raise ValueError("Observation time cannot regress")
        self._queue("ObservationBoundary", time)
        while self.state.events and self.state.events[0].time <= time:
            self.advance_next()

    def legal_actions(self) -> tuple[Action, ...]:
        """Catalogue for future policies: complete transfers; primitives are diagnostic only."""
        candidates = []
        robot = self.state.robot
        if not robot.busy and not self.completed:
            for wafer_id, wafer in self.state.wafers.items():
                if wafer.location == "ROBOT":
                    continue
                route = self._wafers[wafer_id].route
                destinations = route[wafer.stage].chambers if wafer.stage < len(route) else ("OUT",)
                for destination in destinations:
                    action = (Action.unload(wafer_id) if destination == "OUT"
                              else Action.transfer(wafer_id, destination))
                    if self.validate_action(action):
                        candidates.append(action)
            if robot.carrying is not None:
                wafer = self.state.wafers[robot.carrying]
                route = self._wafers[robot.carrying].route
                destinations = route[wafer.stage].chambers if wafer.stage < len(route) else ("OUT",)
                for destination in destinations:
                    place = Action.place(robot.carrying, destination)
                    if self.validate_action(place):
                        candidates.append(place)
                    elif robot.position != destination:
                        # A diagnostic manual pickup can be recovered by moving then placing.
                        chamber = self.state.chambers.get(destination)
                        if chamber is None or (chamber.available and chamber.wafer_id is None
                                               and chamber.reservation is None):
                            candidates.append(Action.move(destination))
        if self.state.events and not self.completed:
            candidates.append(Action.wait())
        return tuple(candidates)

    def detect_deadlock(self) -> dict | None:
        if self.completed or self.state.events or any(
            action.kind != "wait" for action in self.legal_actions()
        ):
            return None
        if self.state.deadlock is None:
            before = self.snapshot()
            waits = []
            for wafer_id, wafer in self.state.wafers.items():
                if wafer.completed_at is not None:
                    continue
                route = self._wafers[wafer_id].route
                targets = route[wafer.stage].chambers if wafer.stage < len(route) else ("OUT",)
                waits.append({"wafer": wafer_id, "source": wafer.location,
                              "required_destinations": list(targets),
                              "rejections": [asdict(self.validate_action(
                                  Action.transfer(wafer_id, target))) for target in targets]})
            self.state.deadlock = {
                "time": self.state.time, "code": "no_progress_action_or_future_event",
                "reason": "Unfinished wafers have no feasible complete transfer or future event",
                "scope": "single_gripper_no_buffer_complete_transfer_model",
                "waits": waits,
            }
            self._record("PotentialDeadlock", before, details=self.state.deadlock)
        return self.state.deadlock

    def _queue(self, kind: str, time: float, **payload) -> None:
        seconds(time, "event timestamp")
        if time < self.state.time:
            raise ValueError("Cannot enqueue an event in the past")
        self._sequence += 1
        heapq.heappush(self.state.events, Event(
            time, PRIORITY.get(kind, 8), self._sequence, kind, **payload))

    def _cancel(self, kind: str, source: str | None = None) -> None:
        self.state.events[:] = [event for event in self.state.events
                                if not (event.kind == kind and (source is None or event.source == source))]
        heapq.heapify(self.state.events)

    def _pick(self):
        robot = self.state.robot
        self._queue("RobotPickStart", self.state.time, wafer_id=robot.active_wafer,
                    source=robot.source, destination=robot.destination,
                    duration=self.config.robot.pick_seconds)

    def _move(self, destination: str, phase: str):
        robot = self.state.robot
        self._queue("RobotMoveStart", self.state.time, wafer_id=robot.active_wafer,
                    source=robot.position, destination=destination, phase=phase,
                    duration=self.config.robot.travel(robot.position, destination))

    def _request_place(self, duration: float):
        robot = self.state.robot
        chamber = self.state.chambers.get(robot.destination)
        robot.place_remaining = duration
        if chamber is not None and not chamber.available:
            robot.phase = "waiting_recovery"
            robot.phase_end = None
            return
        self._queue("RobotPlaceStart", self.state.time, wafer_id=robot.carrying,
                    source=robot.transfer_source, destination=robot.destination,
                    duration=duration)

    def _finish_robot(self, *, placed: bool = False):
        robot = self.state.robot
        robot.busy = False
        robot.phase = "idle"
        robot.phase_end = None
        robot.active_wafer = None
        robot.high_level = False
        robot.source = None
        robot.destination = None
        robot.place_remaining = 0.0
        if placed:
            robot.transfer_start = None
            robot.transfer_source = None

    def _drain_current(self):
        while self.state.events and self.state.events[0].time == self.state.time:
            before = self.snapshot()
            event = heapq.heappop(self.state.events)
            self._handle(event)
            self._assert_state()
            self._record(event.kind, before, event=event)

    def _handle(self, event: Event):
        now = self.state.time
        robot = self.state.robot
        wafer = self.state.wafers.get(event.wafer_id)
        if event.kind in {"RobotPickStart", "RobotMoveStart", "RobotPlaceStart"}:
            phase = {"RobotPickStart": "picking", "RobotPlaceStart": "placing"}.get(
                event.kind, event.phase)
            robot.phase = phase
            robot.phase_end = now + event.duration
            if event.kind == "RobotPickStart":
                wafer.status = "picking"
                if robot.transfer_start is None:
                    robot.transfer_start = now
                    robot.transfer_source = event.source
            elif event.kind == "RobotPlaceStart":
                wafer.status = "placing"
            elif robot.carrying is not None:
                self.state.wafers[robot.carrying].status = "transporting"
            self._queue(event.kind.replace("Start", "Complete"), robot.phase_end,
                        wafer_id=event.wafer_id, source=event.source, destination=event.destination,
                        phase=phase, duration=event.duration, started_at=now)
        elif event.kind == "RobotPickComplete":
            wafer.location = "ROBOT"
            wafer.status = "transporting"
            robot.carrying = event.wafer_id
            if event.source in self.state.chambers:
                chamber = self.state.chambers[event.source]
                chamber.wafer_id = None
                chamber.status = "idle"
                chamber.remaining = 0.0
                chamber.ready_at = None
                chamber.process_started_at = None
            if robot.high_level:
                self._move(robot.destination, "moving_loaded")
                robot.phase = "scheduled"
                robot.phase_end = None
            else:
                self._finish_robot()
        elif event.kind == "RobotMoveComplete":
            robot.position = event.destination
            robot.phase_end = None
            if robot.high_level:
                robot.phase = "scheduled"
                if event.phase == "moving_empty":
                    self._pick()
                else:
                    self._request_place(self.config.robot.place_seconds)
            else:
                self._finish_robot()
        elif event.kind == "RobotPlaceComplete":
            destination = event.destination
            wafer.location = destination
            wafer.transfer_records.append({
                "stage": wafer.stage, "source": robot.transfer_source,
                "destination": destination, "start": robot.transfer_start, "end": now,
            })
            if destination in self.state.chambers:
                chamber = self.state.chambers[destination]
                chamber.wafer_id = event.wafer_id
                chamber.status = "queued"
                chamber.reservation = None
                wafer.status = "queued"
                self._queue("ChamberProcessStart", now, wafer_id=event.wafer_id, source=destination)
            else:
                wafer.status = "unloading_complete"
                self._queue("WaferCompleted", now, wafer_id=event.wafer_id, destination="OUT")
            robot.carrying = None
            self._finish_robot(placed=True)
        elif event.kind == "ChamberProcessStart":
            chamber = self.state.chambers[event.source]
            step = self._wafers[event.wafer_id].route[wafer.stage]
            if chamber.status != "paused":
                chamber.remaining = self._chambers[event.source].processing_time(step.recipe)
                chamber.process_started_at = now
            chamber.status = "processing"
            chamber.ready_at = now + chamber.remaining
            wafer.status = "processing"
            self._queue("ChamberProcessComplete", chamber.ready_at,
                        wafer_id=event.wafer_id, source=event.source,
                        duration=chamber.remaining, started_at=now)
        elif event.kind == "ChamberProcessComplete":
            chamber = self.state.chambers[event.source]
            step = self._wafers[event.wafer_id].route[wafer.stage]
            wafer.processing_records.append({
                "stage": wafer.stage, "recipe": step.recipe, "chamber": event.source,
                "start": chamber.process_started_at, "end": now,
            })
            wafer.stage += 1
            wafer.status = "waiting"
            chamber.status = "blocked"
            chamber.remaining = 0.0
            chamber.ready_at = None
        elif event.kind == "WaferCompleted":
            wafer.completed_at = now
            wafer.status = "completed"
        elif event.kind == "WaferReleased":
            wafer.released = True
            wafer.status = "waiting"
        elif event.kind in {"ChamberUnavailable", "ChamberAvailable"}:
            chamber = self.state.chambers[event.source]
            available = not any(item.chamber_id == event.source and item.start <= now < item.end
                                for item in self.config.downtimes)
            chamber.available = available
            if not available:
                if chamber.status == "processing":
                    self._cancel("ChamberProcessComplete", event.source)
                    chamber.status = "paused"
                    chamber.ready_at = None
                    self.state.wafers[chamber.wafer_id].status = "paused"
                if robot.busy and robot.destination == event.source and robot.phase == "placing":
                    robot.place_remaining = max(0.0, robot.phase_end - now)
                    self._cancel("RobotPlaceComplete")
                    robot.phase = "waiting_recovery"
                    robot.phase_end = None
                    self.state.wafers[robot.carrying].status = "transporting"
            else:
                if chamber.status == "paused":
                    self._queue("ChamberProcessStart", now, wafer_id=chamber.wafer_id,
                                source=event.source)
                if robot.busy and robot.destination == event.source and robot.phase == "waiting_recovery":
                    robot.phase = "scheduled"
                    self._request_place(robot.place_remaining)
        elif event.kind != "ObservationBoundary":
            raise RuntimeError(f"Unhandled event: {event.kind}")

    def _record(self, kind: str, before: dict, *, event: Event | None = None,
                wafer_id=None, source=None, destination=None, details=None):
        if event is not None:
            wafer_id, source, destination = event.wafer_id, event.source, event.destination
        duration = event.duration if event is not None else 0.0
        start = (event.started_at if event is not None and event.started_at is not None
                 else self.state.time)
        end = (self.state.time + duration if kind.endswith("Start") and kind.startswith("Robot")
               else self.state.time)
        if kind == "ChamberProcessStart":
            end = self.state.chambers[source].ready_at
        self.trace.append({
            "index": len(self.trace), "time": self.state.time, "event": kind,
            "start_time": start, "end_time": end,
            "interval_semantics": "planned_end" if kind.endswith("Start") else "actual_end",
            "wafer_id": wafer_id, "source": source, "destination": destination,
            "target_chamber": destination if destination in self.state.chambers else (
                source if kind.startswith("Chamber") else None),
            "robot_position": self.state.robot.position,
            "completed_count": sum(item.completed_at is not None for item in self.state.wafers.values()),
            "state_before": before, "state_after": self.snapshot(), "details": details,
        })

    def _assert_state(self):
        result = self.validate_state()
        if not result:
            raise RuntimeError(result.reason)
