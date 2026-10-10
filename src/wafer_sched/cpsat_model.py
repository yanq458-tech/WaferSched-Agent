"""Exact static macro-transfer model, including reservations and blocking."""

from dataclasses import dataclass
from fractions import Fraction
import math

from ortools.sat.python import cp_model

from .config import EquipmentConfig


class UnsupportedModel(ValueError):
    pass


@dataclass
class TransferVariables:
    wafer_id: str
    stage: int
    source: object
    destination: object
    start: object
    end: object
    pick_end: object
    previous_position: object
    empty: object
    loaded: object


@dataclass
class ProcessVariables:
    wafer_id: str
    stage: int
    chamber: object
    start: object
    end: object
    resource_end: object
    choices: dict


@dataclass
class ModelBundle:
    model: cp_model.CpModel
    config: EquipmentConfig
    scale: int
    horizon: int
    safe_horizon: int
    locations: tuple
    transfers: list
    processes: list
    arcs: dict
    makespan: object
    restricted: bool


def time_scale(config, requested=None):
    if config.downtimes:
        raise UnsupportedModel("Downtime pause/recovery is not supported by the static CP-SAT model")
    if config.robot.pick_seconds <= 0 or config.robot.place_seconds <= 0:
        raise UnsupportedModel("Static CP-SAT requires positive pick and place durations")
    durations = [config.robot.pick_seconds, config.robot.place_seconds, config.robot.move_seconds]
    durations += [value for _, _, value in config.robot.travel_times]
    durations += [wafer.release_seconds for wafer in config.wafers]
    durations += [value for chamber in config.chambers for _, value in chamber.processing_times]
    denominators = [Fraction(str(value)).denominator for value in durations]
    scale = math.lcm(*denominators) if requested is None else requested
    if type(scale) is not int or not 1 <= scale <= 10000:
        raise UnsupportedModel("Exact time scale must be an integer in [1,10000]; no rounding is allowed")
    if any(scale % denominator for denominator in denominators):
        raise UnsupportedModel("Requested tick scale cannot exactly represent equipment times")
    return scale


def ticks(value, scale):
    exact = Fraction(str(value)) * scale
    if exact.denominator != 1:
        raise UnsupportedModel(f"Time {value} is not exactly representable at scale {scale}")
    return int(exact)


def build_model(config: EquipmentConfig, *, ticks_per_second=None, horizon_seconds=None,
                objective_lower_seconds=None, objective_upper_seconds=None) -> ModelBundle:
    scale = time_scale(config, ticks_per_second)
    locations = ("LOAD", "OUT", *(item.chamber_id for item in config.chambers))
    location = {key: index for index, key in enumerate(locations)}
    chamber_config = {item.chamber_id: item for item in config.chambers}
    travel = [ticks(config.robot.travel(left, right), scale) for left in locations for right in locations]
    pick, place = ticks(config.robot.pick_seconds, scale), ticks(config.robot.place_seconds, scale)
    safe = max(ticks(wafer.release_seconds, scale) for wafer in config.wafers)
    for wafer in config.wafers:
        safe += (len(wafer.route) + 1) * (2 * max(travel) + pick + place)
        safe += sum(max(ticks(chamber_config[key].processing_time(step.recipe), scale)
                        for key in step.chambers) for step in wafer.route)
    horizon = safe if horizon_seconds is None else ticks(horizon_seconds, scale)
    if horizon < 0 or horizon >= 2**50:
        raise ValueError("Invalid/oversized scheduling horizon")
    model = cp_model.CpModel()
    transfers, processes, arcs = [], [], {}
    by_wafer = {}
    chamber_intervals = {key: [] for key in chamber_config}
    robot_intervals = []

    def variable(label, lo=0, hi=horizon):
        return model.new_int_var(lo, hi, label)

    def travel_variable(left, right, label):
        index = variable(label + "_index", 0, len(travel) - 1)
        model.add(index == left * len(locations) + right)
        duration = variable(label, 0, max(travel))
        model.add_element(index, travel, duration)
        return duration

    for wafer in config.wafers:
        selected = [model.new_int_var_from_domain(cp_model.Domain.from_values(
            [location[key] for key in step.chambers]), f"chamber_{wafer.wafer_id}_{stage}")
            for stage, step in enumerate(wafer.route)]
        tasks = []
        for stage in range(len(wafer.route) + 1):
            label = f"{wafer.wafer_id}_{stage}"
            source = location["LOAD"] if stage == 0 else selected[stage - 1]
            destination = location["OUT"] if stage == len(wafer.route) else selected[stage]
            start, end, pick_end = variable("start_" + label), variable("end_" + label), variable("pick_end_" + label)
            previous = variable("previous_" + label, 0, len(locations) - 1)
            empty = travel_variable(previous, source, "empty_" + label)
            loaded = travel_variable(source, destination, "loaded_" + label)
            model.add(pick_end == start + empty + pick)
            model.add(end == pick_end + loaded + place)
            size = variable("robot_size_" + label)
            model.add(size == end - start)
            robot_intervals.append(model.new_interval_var(start, size, end, "robot_" + label))
            task = TransferVariables(wafer.wafer_id, stage, source, destination, start, end,
                                     pick_end, previous, empty, loaded)
            tasks.append(task)
            transfers.append(task)
        model.add(tasks[0].start >= ticks(wafer.release_seconds, scale))
        by_wafer[wafer.wafer_id] = tasks
        for stage, step in enumerate(wafer.route):
            process_start = tasks[stage].end
            process_end = variable(f"process_end_{wafer.wafer_id}_{stage}")
            following = tasks[stage + 1]
            model.add(following.start >= process_end)
            resource_end = variable(f"resource_end_{wafer.wafer_id}_{stage}")
            if stage + 1 < len(wafer.route):
                same = model.new_bool_var(f"same_chamber_{wafer.wafer_id}_{stage}")
                model.add(selected[stage] == selected[stage + 1]).only_enforce_if(same)
                model.add(selected[stage] != selected[stage + 1]).only_enforce_if(same.Not())
                # Hand ownership to the next operation of the SAME wafer at accept.
                # The union of reservations/occupation stays continuous, with no gap.
                model.add(resource_end == following.start).only_enforce_if(same)
                model.add(resource_end == following.pick_end).only_enforce_if(same.Not())
            else:
                model.add(resource_end == following.pick_end)
            choices = {}
            for key in step.chambers:
                present = model.new_bool_var(f"assign_{wafer.wafer_id}_{stage}_{key}")
                choices[key] = present
                model.add(selected[stage] == location[key]).only_enforce_if(present)
                model.add(selected[stage] != location[key]).only_enforce_if(present.Not())
                duration = ticks(chamber_config[key].processing_time(step.recipe), scale)
                model.new_optional_interval_var(process_start, duration, process_end, present,
                                                f"processing_{wafer.wafer_id}_{stage}_{key}")
                occupancy = variable(f"occupancy_size_{wafer.wafer_id}_{stage}_{key}")
                model.add(occupancy == resource_end - tasks[stage].start).only_enforce_if(present)
                chamber_intervals[key].append(model.new_optional_interval_var(
                    tasks[stage].start, occupancy, resource_end, present,
                    f"reserved_occupied_{wafer.wafer_id}_{stage}_{key}"))
            model.add_exactly_one(list(choices.values()))
            processes.append(ProcessVariables(wafer.wafer_id, stage, selected[stage], process_start,
                                              process_end, resource_end, choices))
    model.add_no_overlap(robot_intervals)
    for intervals in chamber_intervals.values():
        model.add_no_overlap(intervals)
    circuit = []
    for node, task in enumerate(transfers, 1):
        if task.stage == 0:
            arc = model.new_bool_var(f"arc_0_{node}")
            arcs[0, node] = arc
            circuit.append((0, node, arc))
            model.add(task.previous_position == location[config.robot.initial_position]).only_enforce_if(arc)
        if task.stage == len(by_wafer[task.wafer_id]) - 1:
            arc = model.new_bool_var(f"arc_{node}_0")
            arcs[node, 0] = arc
            circuit.append((node, 0, arc))
        for successor, next_task in enumerate(transfers, 1):
            if node == successor or task.wafer_id == next_task.wafer_id and task.stage >= next_task.stage:
                continue
            arc = model.new_bool_var(f"arc_{node}_{successor}")
            arcs[node, successor] = arc
            circuit.append((node, successor, arc))
            model.add(next_task.start >= task.end).only_enforce_if(arc)
            model.add(next_task.previous_position == task.destination).only_enforce_if(arc)
    model.add_circuit(circuit)
    makespan = variable("makespan")
    model.add_max_equality(makespan, [tasks[-1].end for tasks in by_wafer.values()])
    if objective_lower_seconds is not None:
        model.add(makespan >= ticks(objective_lower_seconds, scale))
    if objective_upper_seconds is not None:
        model.add(makespan <= ticks(objective_upper_seconds, scale))
    model.minimize(makespan)
    return ModelBundle(model, config, scale, horizon, safe, locations, transfers, processes, arcs,
                       makespan, horizon < safe or objective_lower_seconds is not None or objective_upper_seconds is not None)


def add_verified_hint(bundle, simulator):
    """Only a completed, original-engine-validated incumbent can constrain the UB."""
    if simulator.config != bundle.config or not simulator.completed or not simulator.validate_state():
        raise ValueError("Hint must be a validated complete run of the identical configuration")
    nodes = {(task.wafer_id, task.stage): index for index, task in enumerate(bundle.transfers, 1)}
    model, scale = bundle.model, bundle.scale
    locations = {name: index for index, name in enumerate(bundle.locations)}

    def hint_time(value):
        result = round(value * scale)
        if not math.isclose(result / scale, value, abs_tol=1e-7, rel_tol=0):
            raise ValueError("Incumbent does not lie on exact configured tick grid")
        return result

    order, counters = [], {}
    previous = locations[bundle.config.robot.initial_position]
    for row in simulator.trace:
        if row["event"] != "ActionAccepted":
            continue
        action = row["details"]["action"]
        if action["kind"] not in {"transfer", "unload"}:
            raise ValueError("Hint must use complete macro transfers")
        key = action["wafer_id"]
        stage = counters.get(key, 0)
        counters[key] = stage + 1
        node = nodes[key, stage]
        task = bundle.transfers[node - 1]
        record = simulator.state.wafers[key].transfer_records[stage]
        model.add_hint(task.start, hint_time(record["start"]))
        model.add_hint(task.end, hint_time(record["end"]))
        model.add_hint(task.previous_position, previous)
        pick_end = record["start"] + bundle.config.robot.travel(bundle.locations[previous], record["source"]) + bundle.config.robot.pick_seconds
        model.add_hint(task.pick_end, hint_time(pick_end))
        previous = locations[record["destination"]]
        order.append(node)
    active = set(zip([0] + order, order + [0]))
    for edge, arc in bundle.arcs.items():
        model.add_hint(arc, int(edge in active))
    for operation in bundle.processes:
        record = simulator.state.wafers[operation.wafer_id].processing_records[operation.stage]
        model.add_hint(operation.chamber, locations[record["chamber"]])
        model.add_hint(operation.end, hint_time(record["end"]))
        for key, presence in operation.choices.items():
            model.add_hint(presence, int(key == record["chamber"]))
    completion = max(wafer.completed_at for wafer in simulator.state.wafers.values())
    if hint_time(completion) <= bundle.horizon:
        model.add(bundle.makespan <= hint_time(completion))
        model.add_hint(bundle.makespan, hint_time(completion))
