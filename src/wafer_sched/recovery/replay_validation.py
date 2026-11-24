"""Recovery-only state checking with optional replay memoization."""
import math

from ..config import EquipmentConfig, PORTS
from ..equipment import EquipmentState
from ..verification import ValidationResult


_OCCUPIED_STATUSES = {"queued": ("queued",), "processing": ("processing",),
                      "paused": ("paused",), "blocked": ("waiting", "picking")}


def validate_state(state: EquipmentState, config: EquipmentConfig, *, wafer_cache=None, config_tables=None) -> ValidationResult:
    errors = []
    if not math.isfinite(state.time) or state.time < 0:
        errors.append("Simulation time must be finite and nonnegative")
    if config_tables is None:
        configured_wafers = {item.wafer_id: item for item in config.wafers}
        configured_chambers = {item.chamber_id: item for item in config.chambers}
        completion_sources = None
    else:
        configured_wafers, configured_chambers = config_tables
        completion_sources = {e.source for e in state.events if e.kind == "ChamberProcessComplete"}
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
                if wafer.status not in _OCCUPIED_STATUSES.get(chamber.status, ()):
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
            queued = (chamber_id in completion_sources if completion_sources is not None else
                      any(e.kind == "ChamberProcessComplete" and e.source == chamber_id for e in state.events))
            if not queued:
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
    locations = set(state.chambers).union(PORTS, ("ROBOT",))
    for wafer_id, wafer in state.wafers.items():
        specification = configured_wafers.get(wafer_id)
        if specification is None:
            continue
        if wafer.location not in locations:
            errors.append(f"{wafer_id}: unknown wafer location")
        if wafer.location in state.chambers and state.chambers[wafer.location].wafer_id != wafer_id:
            errors.append(f"{wafer_id}: wafer has no matching chamber occupation")
        if wafer.location == "ROBOT" and robot.carrying != wafer_id:
            errors.append(f"{wafer_id}: robot location has no matching payload")
        # Resource occupancy above always uses the current state. The remaining
        # checks depend only on this wafer, its route, and an upper clock bound.
        if wafer_cache is not None:
            key = (wafer.location, wafer.stage, wafer.status, wafer.completed_at, wafer.released)
            old = wafer_cache.get(wafer_id)
            if (old and old[0] is specification and old[1] == key and old[2] <= state.time
                    and old[3] == wafer.processing_records and old[4] == wafer.transfer_records):
                continue
            before_errors = len(errors)
            wafer_cache.pop(wafer_id, None)
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
        if wafer_cache is not None and len(errors) == before_errors:
            wafer_cache[wafer_id] = (specification, key, state.time,
                                     [r.copy() for r in wafer.processing_records],
                                     [r.copy() for r in wafer.transfer_records])
    sequences = set()
    for event in state.events:
        if not math.isfinite(event.time) or event.time < state.time - 1e-9:
            errors.append("Event queue contains an invalid or past timestamp")
        if event.sequence in sequences:
            errors.append("Event queue contains duplicate stable-order ids")
        sequences.add(event.sequence)
    return ValidationResult(not errors, "ok" if not errors else "invalid_state",
                            "; ".join(errors), tuple(errors))
