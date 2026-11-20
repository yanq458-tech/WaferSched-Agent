"""Solver conclusions and independent replay are recorded separately."""

from dataclasses import asdict, dataclass
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from ..config import seconds
from ..cpsat_model import ticks
from ..cpsat_solver import SolverOptions
from .model import build_recovery_model
from .replay import replay_recovery


@dataclass
class RecoveryResult:
    metadata: dict
    schedule: dict | None
    replay: dict | None
    log: str
    model_proto: str

    @property
    def feasible(self):
        return self.metadata["status"] in {"OPTIMAL", "FEASIBLE"} and bool(
            self.replay and self.replay["valid"])

    def summary(self):
        return {**self.metadata, "schedule": self.schedule,
                "verification": ({k: v for k, v in self.replay.items() if k != "trace"}
                                 if self.replay else None)}


def read_witness(problem, bundle, solver, repair_delay):
    transfers = []
    for task in bundle.tasks:
        row = {k: (v if k in {"wafer_id", "stage", "initially_carried"} else
                   bundle.locations[solver.value(v)] if k in {"source", "destination"}
                   else solver.value(v)) for k, v in task.items()}
        transfers.append(row)
    transfers.sort(key=lambda t: t["pick_start"])
    processes = [{k: (v if k in {"wafer_id", "stage"} else
                      bundle.locations[solver.value(v)] if k == "chamber" else solver.value(v))
                  for k, v in task.items()} for task in bundle.processes]
    schedule = {"ticks_per_second": bundle.scale, "transfers": transfers,
                "processes": processes, "makespan_tick": solver.value(bundle.makespan)}
    replay = replay_recovery(problem, repair_delay, schedule)
    return schedule, replay


def solve_recovery(problem, repair_delay, options=None, *, minimize_makespan=True,
                   use_joint_bound=False, warm_schedule=None, use_pickup_bound=False):
    options = options or SolverOptions(max_seconds=5, log_search=True)
    if any(x is not None for x in (options.horizon_seconds, options.objective_lower_seconds,
                                   options.objective_upper_seconds)):
        raise ValueError("Recovery uses its proved complete horizon, not user-restricted horizons")
    if options.ticks_per_second not in (None, problem.scale):
        raise ValueError("Use the exact recovery input scale")
    seconds(repair_delay, "repair_delay")
    repair_tick = ticks(repair_delay, problem.scale)
    started = perf_counter()
    if use_pickup_bound:
        from .bounds import pickup_conflict
        conflict = pickup_conflict(problem)
        if conflict:
            return RecoveryResult({"status": "INFEASIBLE", "proof_source": "initial_pickup_workload",
                "certificate": conflict, "repair_delay_seconds": repair_delay,
                "total_seconds": perf_counter()-started, "solver_seconds": 0.0,
                "branches": 0, "conflicts": 0}, None, None, "", "")
    if use_joint_bound:
        from .bounds import joint_bound
        certificate = joint_bound(problem)
        if certificate and repair_tick > certificate["upper_tick"]:
            return RecoveryResult({"status": "INFEASIBLE", "proof_source": "joint_necessary_bound",
                "certificate": certificate, "repair_delay_seconds": repair_delay,
                "total_seconds": perf_counter()-started, "solver_seconds": 0.0,
                "branches": 0, "conflicts": 0, "options": asdict(options)}, None, None, "", "")
    bundle = build_recovery_model(problem, repair_tick, minimize_makespan=minimize_makespan)
    hinted = False
    if warm_schedule and replay_recovery(problem, repair_delay, warm_schedule)["valid"]:
        by_key = {(t["wafer_id"], t["stage"]): t for t in warm_schedule["transfers"]}
        for task in bundle.tasks:
            row = by_key[task["wafer_id"], task["stage"]]
            for key in ("pick_start", "pick_end", "place_start", "place_end"):
                bundle.model.add_hint(task[key], row[key])
        hinted = True
    validation = bundle.model.validate()
    if validation:
        raise RuntimeError(validation)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_seconds
    solver.parameters.random_seed = options.seed
    solver.parameters.num_search_workers = options.workers
    solver.parameters.log_search_progress = options.log_search
    solver.parameters.log_to_stdout = False
    logs = []
    solver.log_callback = logs.append
    build_seconds = perf_counter() - started
    status = solver.solve(bundle.model)
    name = solver.status_name(status)
    feasible = status in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    schedule, replay = None, None
    if feasible:
        schedule, replay = read_witness(problem, bundle, solver, repair_delay)
        if not replay["valid"]:
            name = "VERIFICATION_FAILED"
    metadata = {
        "status": name, "solver_status": solver.status_name(status),
        "proof_source": "CP-SAT_complete_supported_model", "repair_delay_seconds": repair_delay,
        "makespan_seconds": schedule["makespan_tick"] / bundle.scale if schedule else None,
        "makespan_optimal": name == "OPTIMAL" and minimize_makespan,
        "best_makespan_bound_seconds": solver.best_objective_bound / bundle.scale
        if minimize_makespan and status in {cp_model.OPTIMAL, cp_model.FEASIBLE} else None,
        "ticks_per_second": bundle.scale, "horizon_tick": bundle.horizon,
        "finite_boundary_cap_tick": bundle.finite_cap,
        "branches": solver.num_branches, "conflicts": solver.num_conflicts,
        "build_seconds": build_seconds, "solver_seconds": solver.wall_time,
        "total_seconds": perf_counter() - started, "ortools_version": ortools.__version__,
        "options": asdict(options), "joint_bound_enabled": use_joint_bound,
        "verified_time_hint": hinted,
        "scope": ("qualified_finished_wafer_in_failed_chamber" if problem.allows_occupied()
                  else "single_empty_failed_chamber_idle_robot_warm_WIP_primitive_transfers"),
    }
    return RecoveryResult(metadata, schedule, replay,
                          "".join(logs) + "\n" + solver.response_stats(), str(bundle.model.proto))
