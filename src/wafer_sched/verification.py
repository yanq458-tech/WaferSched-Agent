"""Independent, read-only physical action and state validation."""

from dataclasses import dataclass
import math

from .actions import Action
from .config import EquipmentConfig, PORTS
from .equipment import EquipmentState


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    code: str = "ok"
    reason: str = ""
    errors: tuple[str, ...] = ()

    def __bool__(self):
        return self.valid


def reject(code: str, reason: str) -> ValidationResult:
    return ValidationResult(False, code, reason, (reason,))


def validate_action(state: EquipmentState, config: EquipmentConfig,
                    action: Action) -> ValidationResult:
    if action.kind not in {"transfer", "unload", "wait", "pick", "move", "place"}:
        return reject("unknown_action", "Unsupported action kind")
    if all(wafer.completed_at is not None for wafer in state.wafers.values()):
        return reject("batch_completed", "No new actions are permitted after the batch completes")
    if action.kind == "wait":
        if not state.events:
            return reject("no_future_event", "Waiting cannot advance without a queued event")
        return ValidationResult(True)
    robot = state.robot
    if robot.busy:
        return reject("robot_busy", "Robot already owns an unfinished action")
    locations = set(state.chambers) | set(PORTS)
    if action.kind == "move":
        if action.destination not in locations:
            return reject("unknown_destination", "Move destination is not an equipment location")
        return ValidationResult(True)
    if action.kind == "place" and robot.carrying is None:
        return reject("robot_not_carrying", "Cannot place a wafer from an empty gripper")
    if action.kind != "place" and robot.carrying is not None:
        return reject("gripper_occupied", "Single-wafer gripper is already occupied")
    if action.wafer_id not in state.wafers:
        return reject("unknown_wafer", "Wafer id is not in this batch")
    wafer = state.wafers[action.wafer_id]
    specification = next(item for item in config.wafers if item.wafer_id == action.wafer_id)
    if not wafer.released:
        return reject("wafer_not_released", "Wafer has not arrived at the load unit")
    if wafer.completed_at is not None:
        return reject("wafer_completed", "A completed wafer cannot be processed again")
    source = action.source or wafer.location
    if action.kind != "place":
        if source in state.chambers and state.chambers[source].wafer_id is None:
            return reject("empty_chamber", "Cannot pick from an empty chamber")
        if source != wafer.location or source not in locations or source == "OUT":
            return reject("source_mismatch", "Wafer is not at a valid pickup source")
        if source in state.chambers and state.chambers[source].status != "blocked":
            return reject("process_unfinished", "Chamber processing must finish before pickup")
        if action.kind == "pick":
            if robot.position != source:
                return reject("robot_position", "Explicit pick requires robot at the source")
            return ValidationResult(True)
    else:
        if robot.carrying != action.wafer_id or wafer.location != "ROBOT":
            return reject("payload_mismatch", "Robot is not carrying the requested wafer")
        if robot.position != action.destination:
            return reject("robot_position", "Explicit place requires robot at the destination")
    destination = action.destination
    if destination not in locations or destination == "LOAD":
        return reject("unknown_destination", "Placement requires a chamber or the output port")
    if destination == "OUT":
        if wafer.stage != len(specification.route):
            return reject("route_incomplete", "Cannot unload before all process stages finish")
    else:
        if wafer.stage >= len(specification.route):
            return reject("route_complete", "All process stages already finished; unload next")
        if destination not in specification.route[wafer.stage].chambers:
            return reject("route_order", "Destination does not execute the next required stage")
        chamber = state.chambers[destination]
        if not chamber.available:
            return reject("chamber_unavailable", "Unavailable chamber cannot receive a new wafer")
        own_source = (action.kind in {"transfer", "unload"} and source == destination
                      and chamber.wafer_id == action.wafer_id and chamber.status == "blocked")
        if chamber.wafer_id is not None and not own_source:
            return reject("chamber_full", "Destination chamber capacity is already occupied")
        if chamber.reservation is not None:
            return reject("chamber_reserved", "Destination is reserved by an unfinished transfer")
    if action.kind == "unload" and destination != "OUT":
        return reject("unload_destination", "Unload must end at the output port")
    return ValidationResult(True)


def validate_state(state: EquipmentState, config: EquipmentConfig) -> ValidationResult:
    errors = []
    if not math.isfinite(state.time) or state.time < 0:
        errors.append("Simulation time must be finite and nonnegative")
    configured_wafers = {item.wafer_id: item for item in config.wafers}
    configured_chambers = {item.chamber_id: item for item in config.chambers}
    if set(state.wafers) != set(configured_wafers):
        errors.append("Wafer conservation failed: missing or extra wafer")
    if set(state.chambers) != set(configured_chambers):
        errors.append("Chamber identity set differs from equipment configuration")
    robot = state.robot
    if robot.position not in {*state.chambers, *PORTS}:
        errors.append("Robot position is outside the equipment")
    if robot.busy == (robot.phase == "idle"):
        errors.append("Robot busy flag and phase disagree")
    if robot.phase not in {"idle", "scheduled", "picking", "moving_empty", "moving_loaded",
                            "placing", "waiting_recovery"}:
        errors.append("Unknown robot action phase")
    if robot.phase_end is not None and not math.isfinite(robot.phase_end):
        errors.append("Robot phase end must be finite")
    if robot.phase_end is not None and robot.phase_end < state.time - 1e-9:
        errors.append("Robot phase end is in the past")
    physical = []
    for chamber_id, chamber in state.chambers.items():
        if chamber.status not in {"idle", "queued", "processing", "paused", "blocked"}:
            errors.append(f"{chamber_id}: unknown chamber status")
        if chamber.wafer_id is not None:
            physical.append(chamber.wafer_id)
            if chamber.wafer_id not in state.wafers:
                errors.append(f"{chamber_id}: unknown occupying wafer")
            elif state.wafers[chamber.wafer_id].location != chamber_id:
                errors.append(f"{chamber_id}: wafer location and chamber occupation disagree")
            else:
                wafer = state.wafers[chamber.wafer_id]
                statuses = {"queued": {"queued"}, "processing": {"processing"},
                            "paused": {"paused"}, "blocked": {"waiting", "picking"}}
                if wafer.status not in statuses.get(chamber.status, set()):
                    errors.append(f"{chamber_id}: wafer/chamber processing statuses disagree")
                specification = configured_wafers.get(chamber.wafer_id)
                stage = wafer.stage - int(chamber.status == "blocked")
                if specification is not None and (not 0 <= stage < len(specification.route)
                        or chamber_id not in specification.route[stage].chambers):
                    errors.append(f"{chamber_id}: occupancy violates wafer process route")
            if chamber.status == "idle":
                errors.append(f"{chamber_id}: occupied chamber cannot be idle")
        elif chamber.status != "idle":
            errors.append(f"{chamber_id}: empty chamber has an active process state")
        if not math.isfinite(chamber.remaining) or chamber.remaining < 0:
            errors.append(f"{chamber_id}: remaining processing time is invalid")
        if chamber.status == "processing":
            if not chamber.available or chamber.ready_at is None:
                errors.append(f"{chamber_id}: active processing lacks availability/end time")
            elif not math.isclose(chamber.remaining, max(0, chamber.ready_at - state.time),
                                  abs_tol=1e-9):
                errors.append(f"{chamber_id}: remaining processing time disagrees with clock")
            if not any(event.kind == "ChamberProcessComplete"
                       and event.source == chamber_id for event in state.events):
                errors.append(f"{chamber_id}: processing lacks a completion event")
        if chamber.reservation is not None:
            if chamber.reservation not in state.wafers or not robot.busy:
                errors.append(f"{chamber_id}: invalid transfer reservation")
            elif robot.destination != chamber_id or robot.active_wafer != chamber.reservation:
                errors.append(f"{chamber_id}: reservation does not belong to robot action")
    if robot.carrying is not None:
        physical.append(robot.carrying)
        if robot.carrying not in state.wafers or state.wafers[robot.carrying].location != "ROBOT":
            errors.append("Robot payload disagrees with wafer location")
    if len(physical) != len(set(physical)):
        errors.append("A wafer occupies multiple physical resources")
    for wafer_id, wafer in state.wafers.items():
        specification = configured_wafers.get(wafer_id)
        if specification is None:
            continue
        if wafer.location not in {*state.chambers, *PORTS, "ROBOT"}:
            errors.append(f"{wafer_id}: unknown wafer location")
        if wafer.location in state.chambers and state.chambers[wafer.location].wafer_id != wafer_id:
            errors.append(f"{wafer_id}: wafer has no matching chamber occupation")
        if wafer.location == "ROBOT" and robot.carrying != wafer_id:
            errors.append(f"{wafer_id}: robot location has no matching payload")
        if wafer.location == "LOAD" and (wafer.stage != 0 or wafer.transfer_records):
            errors.append(f"{wafer_id}: processed wafer cannot reappear in the input queue")
        if wafer.stage != len(wafer.processing_records) or not 0 <= wafer.stage <= len(specification.route):
            errors.append(f"{wafer_id}: stage counter/processing records violate route order")
        for index, record in enumerate(wafer.processing_records):
            if index >= len(specification.route):
                errors.append(f"{wafer_id}: duplicate/extra process stage")
                continue
            step = specification.route[index]
            if (record.get("stage") != index or record.get("chamber") not in step.chambers
                    or record.get("recipe") != step.recipe):
                errors.append(f"{wafer_id}: processing record violates specified route")
            if record.get("end", -1) < record.get("start", 0):
                errors.append(f"{wafer_id}: process record has negative duration")
            if record.get("end", 0) > state.time:
                errors.append(f"{wafer_id}: process record ends in the future")
        previous_destination = "LOAD"
        previous_end = 0.0
        for record in wafer.transfer_records:
            if (record.get("source") != previous_destination
                    or record.get("start", -1) < previous_end
                    or record.get("end", -1) < record.get("start", 0)
                    or record.get("end", 0) > state.time):
                errors.append(f"{wafer_id}: transfer record location/time continuity failed")
            previous_destination = record.get("destination")
            previous_end = record.get("end", 0)
        if wafer.completed_at is not None:
            if wafer.location != "OUT" or wafer.stage != len(specification.route):
                errors.append(f"{wafer_id}: completed wafer lacks full route or output location")
            if wafer.status != "completed" or not 0 <= wafer.completed_at <= state.time:
                errors.append(f"{wafer_id}: completion status/time is invalid")
            if previous_end != wafer.completed_at:
                errors.append(f"{wafer_id}: completion time differs from final placement")
            expected = len(specification.route) + 1
            records = wafer.transfer_records
            if len(records) != expected:
                errors.append(f"{wafer_id}: completed wafer lacks full transfer records")
            for index, record in enumerate(records):
                destinations = (specification.route[index].chambers
                                if index < len(specification.route) else ("OUT",))
                if record.get("stage") != index or record.get("destination") not in destinations:
                    errors.append(f"{wafer_id}: completed transfer records violate route order")
        if not wafer.released and (wafer.location != "LOAD" or wafer.stage != 0):
            errors.append(f"{wafer_id}: unreleased wafer moved or processed")
    sequences = set()
    for event in state.events:
        if not math.isfinite(event.time) or event.time < state.time - 1e-9:
            errors.append("Event queue contains an invalid or past timestamp")
        if event.sequence in sequences:
            errors.append("Event queue contains duplicate stable-order ids")
        sequences.add(event.sequence)
    return ValidationResult(not errors, "ok" if not errors else "invalid_state",
                            "; ".join(errors), tuple(errors))
