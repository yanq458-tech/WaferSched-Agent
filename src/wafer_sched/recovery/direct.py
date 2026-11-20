"""Direct lexicographic optimization. All public delays are relative to the incident."""

from time import perf_counter
from ortools.sat.python import cp_model

from ..cpsat_model import UnsupportedModel, ticks
from ..cpsat_solver import SolverOptions
from .conflict_evidence import best_bound, verify_bound
from .continuation import BrokenDeadline, delta
from .dispatch import replay_incident
from .model import build_recovery_model
from .replay import replay_recovery
from .solver import read_witness, solve_recovery


def direct(incident, budget=5, *, cuts=True, incumbent=None):
    start = perf_counter()
    deadline = start + budget
    if budget < 0:
        raise ValueError("Negative budget")
    try:
        p, prefix = incident.prepare()
    except UnsupportedModel as exc:
        return dict(status="UNSUPPORTED", reason=str(exc))
    except BrokenDeadline as exc:
        return dict(status="INFEASIBLE_AT_ZERO", reason=str(exc))
    if p is None:
        return dict(
            status="UNBOUNDED", verification_valid=True, makespan_seconds=prefix["completion_delay"]
        )
    offset, scale = prefix["offset"], p.scale
    out = dict(
        status="UNKNOWN",
        latest_repair_delay_seconds=None,
        verified_feasible_lower_seconds=None,
        finite_upper_seconds=None,
        makespan_optimal=False,
        verification_valid=False,
        trace=[],
    )
    if perf_counter() >= deadline:
        return out
    cert = best_bound(p) if cuts else None
    try:
        bundle = build_recovery_model(p, 0, maximize_repair=True)
    except UnsupportedModel as exc:
        return dict(status="UNSUPPORTED", reason=str(exc))
    if cert:
        if not verify_bound(p, cert):
            raise ValueError("Invalid upper-bound certificate")
        out["certificate"] = cert
        bundle.model.add(bundle.repair_variable <= cert["upper_tick"])
        out["finite_upper_seconds"] = offset + cert["upper_tick"] / scale
    if incumbent and incumbent.get("verification_valid"):
        schedule = incumbent["best"]["schedule"]

        delay = max(0, delta(incumbent["witness_repair_delay_seconds"], offset))
        if schedule["ticks_per_second"] == scale and replay_recovery(p, delay, schedule)["valid"]:
            lower = min(ticks(delay, scale), bundle.finite_cap + 1)
            bundle.model.add(bundle.repair_variable >= lower)
            bundle.model.add_hint(bundle.repair_variable, lower)
            by_key = {(t["wafer_id"], t["stage"]): t for t in schedule["transfers"]}
            for task in bundle.tasks:
                row = by_key[(task["wafer_id"], task["stage"])]
                for key in ("pick_start", "pick_end", "place_start", "place_end"):
                    if 0 <= row[key] <= bundle.horizon:
                        bundle.model.add_hint(task[key], row[key])
            out["incumbent_hint"] = True
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = max(0, deadline - perf_counter())
    status = solver.solve(bundle.model)
    out["trace"].append(
        dict(
            objective="max_repair",
            status=solver.status_name(status),
            branches=solver.num_branches,
            seconds=solver.wall_time,
        )
    )
    if status == cp_model.INFEASIBLE:
        if out.get("incumbent_hint"):
            raise RuntimeError("Direct model contradicts a verified incumbent")
        out["status"] = "INFEASIBLE_AT_ZERO"
        return out
    if status == cp_model.MODEL_INVALID:
        raise ValueError(bundle.model.validate() or "CP-SAT rejected direct model")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return out
    tick = solver.value(bundle.repair_variable)
    delay = tick / scale
    schedule, replay = read_witness(p, bundle, solver, delay)
    if not replay["valid"]:
        raise ValueError("Direct witness failed suffix replay")
    best = dict(schedule=schedule, verification={k: v for k, v in replay.items() if k != "trace"})
    finite = tick <= bundle.finite_cap and status == cp_model.OPTIMAL
    if tick == bundle.finite_cap + 1:
        out["status"] = "UNBOUNDED"
    elif finite:
        out.update(status="FINITE", latest_repair_delay_seconds=offset + delay)
    if solver.best_objective_bound <= bundle.finite_cap:
        out["finite_upper_seconds"] = offset + solver.best_objective_bound / scale
    if finite and deadline > perf_counter():
        opt = solve_recovery(
            p,
            delay,
            SolverOptions(max_seconds=max(0, deadline - perf_counter())),
            warm_schedule=schedule,
        )
        out["trace"].append(
            dict(
                objective="min_makespan",
                status=opt.metadata["status"],
                branches=opt.metadata["branches"],
                seconds=opt.metadata["solver_seconds"],
            )
        )
        if opt.feasible and opt.schedule["makespan_tick"] <= schedule["makespan_tick"]:
            best = opt.summary()
            out["makespan_optimal"] = opt.metadata["makespan_optimal"]
        elif opt.metadata["status"] in {"INFEASIBLE", "VERIFICATION_FAILED"}:
            raise RuntimeError("Second objective contradicts boundary witness")
    out.update(
        verification_valid=True,
        best=best,
        verified_feasible_lower_seconds=offset + delay,
        witness_repair_delay_seconds=offset + delay,
        makespan_seconds=offset + best["schedule"]["makespan_tick"] / scale,
    )
    replay_incident(incident, prefix, out, best)
    return out
