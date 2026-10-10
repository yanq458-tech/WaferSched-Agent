"""Solver metadata is distinct from physical replay validity."""

from dataclasses import dataclass, asdict
import math
from time import perf_counter

from ortools.sat.python import cp_model
import ortools

from .cpsat_model import build_model, add_verified_hint


@dataclass(frozen=True)
class SolverOptions:
    max_seconds: float = 5.0
    seed: int = 0
    workers: int = 1
    ticks_per_second: int | None = None
    horizon_seconds: float | None = None
    objective_lower_seconds: float | None = None
    objective_upper_seconds: float | None = None
    log_search: bool = True

    def __post_init__(self):
        if isinstance(self.max_seconds, bool) or not math.isfinite(self.max_seconds) or self.max_seconds < 0:
            raise ValueError("Solver time limit must be finite and nonnegative")
        if type(self.workers) is not int or self.workers <= 0 or type(self.seed) is not int or self.seed < 0:
            raise ValueError("Workers must be positive and seed nonnegative integers")


@dataclass
class SolveResult:
    metadata: dict
    schedule: dict | None
    log: str


def solve_schedule(config, options=SolverOptions(), *, incumbent=None):
    started = perf_counter()
    bundle = build_model(config, ticks_per_second=options.ticks_per_second,
                         horizon_seconds=options.horizon_seconds,
                         objective_lower_seconds=options.objective_lower_seconds,
                         objective_upper_seconds=options.objective_upper_seconds)
    if incumbent is not None:
        add_verified_hint(bundle, incumbent)
    build_seconds = perf_counter() - started
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_seconds
    solver.parameters.random_seed = options.seed
    solver.parameters.num_search_workers = options.workers
    solver.parameters.log_search_progress = options.log_search
    solver.parameters.log_to_stdout = False
    logs = []
    solver.log_callback = logs.append
    status = solver.solve(bundle.model)
    feasible = status in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    scale = bundle.scale
    objective = solver.objective_value / scale if feasible else None
    bound = solver.best_objective_bound / scale if status in {cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN} else None
    gap = (max(0.0, objective - bound) / abs(objective) if objective else 0.0) if feasible else None
    metadata = {
        "status": solver.status_name(status), "objective_seconds": objective,
        "best_bound_seconds": bound, "absolute_gap_seconds": max(0.0, objective - bound) if feasible else None,
        "relative_gap": gap, "build_seconds": build_seconds, "solver_seconds": solver.wall_time,
        "total_seconds": perf_counter() - started, "deterministic_time": solver.response_proto.deterministic_time,
        "branches": solver.num_branches, "conflicts": solver.num_conflicts,
        "ortools_version": ortools.__version__, "options": asdict(options),
        "ticks_per_second": scale, "horizon_seconds": bundle.horizon / scale,
        "safe_serial_horizon_seconds": bundle.safe_horizon / scale,
        "restricted_model": bundle.restricted, "transfer_count": len(bundle.transfers),
        "arc_count": len(bundle.arcs), "variable_count": len(bundle.model.proto.variables),
        "constraint_count": len(bundle.model.proto.constraints),
        "scope": "static_empty_initial_equipment_single_gripper_complete_transfers_no_faults_exact_ticks",
        "model_validation": bundle.model.validate(), "incumbent_hint": incumbent is not None,
    }
    schedule = None
    if feasible:
        transfers = []
        for task in bundle.transfers:
            source, dest = bundle.locations[solver.value(task.source)], bundle.locations[solver.value(task.destination)]
            transfers.append({"wafer_id": task.wafer_id, "stage": task.stage,
                              "kind": "unload" if dest == "OUT" else "transfer", "source": source, "destination": dest,
                              "start_tick": solver.value(task.start), "end_tick": solver.value(task.end),
                              "pick_end_tick": solver.value(task.pick_end),
                              "previous_position": bundle.locations[solver.value(task.previous_position)],
                              "empty_ticks": solver.value(task.empty), "loaded_ticks": solver.value(task.loaded)})
        transfers.sort(key=lambda task: (task["start_tick"], task["wafer_id"], task["stage"]))
        processes = [{"wafer_id": task.wafer_id, "stage": task.stage,
                      "chamber": bundle.locations[solver.value(task.chamber)],
                      "start_tick": solver.value(task.start), "end_tick": solver.value(task.end),
                      "logical_resource_end_tick": solver.value(task.resource_end)} for task in bundle.processes]
        schedule = {"schema_version": 1, "ticks_per_second": scale,
                    "makespan_tick": solver.value(bundle.makespan), "transfers": transfers, "processes": processes}
    return SolveResult(metadata, schedule, "".join(logs) + "\n" + solver.response_stats())
