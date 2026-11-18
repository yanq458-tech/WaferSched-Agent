"""Schema-2 public API. External times in seconds relative to the fault."""

from fractions import Fraction
from time import perf_counter

from ..config import seconds
from ..cpsat_model import UnsupportedModel
from ..cpsat_solver import SolverOptions
from ..actions import Action
from .agent import run_recovery_agent
from .boundary import repair_boundary
from .continuation import BrokenDeadline, checks, delta
from .solver import solve_recovery


def dispatch_window(result, elapsed_since_fault):
    """Check a supplied equipment clock just before executing a saved witness."""
    seconds(elapsed_since_fault, "elapsed_since_fault")
    if not result.get("verification_valid"):
        return {"status": "NO_VERIFIED_PLAN"}
    steps = (result.get("best") or {}).get("verification", {}).get("decisions", [])
    if not steps:
        return {"status": "NO_NEW_COMMAND"}
    first = delta(steps[0]["time"], result["prefix"]["fault_time"])
    return {
        "status": "STALE_PLAN" if elapsed_since_fault > first else "ON_TIME",
        "first_command_delay_seconds": first,
        "elapsed_since_fault": elapsed_since_fault,
    }


def recover(
    incident, mode="agent", *, repair=0, optimized=True, per_query=2, total=30, max_rounds=64
):
    if mode not in {"agent", "boundary", "solve"}:
        raise ValueError("Unknown operation")
    for value in (repair, per_query, total):
        seconds(value, "budget or repair time")
    started = perf_counter()
    try:
        problem, prefix = incident.prepare()
        if problem is not None and mode == "solve":
            from math import lcm

            problem.clock_scale = lcm(problem.clock_scale, Fraction(str(repair)).denominator)
            problem.scale
    except UnsupportedModel as e:
        return {"status": "UNSUPPORTED", "reason": str(e)}
    except BrokenDeadline as e:
        return {
            "status": "INFEASIBLE" if mode == "solve" else "INFEASIBLE_AT_ZERO",
            "proof_source": "committed_quality_violation",
            "reason": str(e),
        }
    out = {
        "prefix": prefix,
        "time_origin": "fault",
        "monotonicity": "fixed prefix, waiting allowed, repair only releases loads and sealed pickups",
    }
    offset = prefix["offset"]
    if problem is None:
        return {
            **out,
            "status": "OPTIMAL" if mode == "solve" else "UNBOUNDED",
            "verification_valid": True,
            "makespan_optimal": True,
            "makespan_seconds": prefix["completion_delay"],
        }

    def remaining():
        return max(0, total - (perf_counter() - started))

    def options():
        return SolverOptions(max_seconds=min(per_query, remaining()))

    if mode == "solve":
        result = solve_recovery(
            problem,
            max(0, delta(repair, offset)),
            options(),
            use_joint_bound=optimized,
            use_pickup_bound=optimized,
        )
        out.update(status=result.metadata["status"], best=result.summary())
    else:
        if mode == "agent":
            if per_query <= 0 or remaining() <= 0:
                return {**out, "status": "UNKNOWN", "stop_reason": "budget_exhausted"}
            allocation = min(per_query, 0.05 * len(problem.config.wafers))
            boundary = run_recovery_agent(
                problem,
                total_seconds=remaining(),
                initial_seconds=allocation,
                max_query_seconds=per_query,
                max_rounds=max_rounds,
                enhanced=optimized,
            )
        else:
            boundary = repair_boundary(
                problem,
                options(),
                total_seconds=remaining(),
                use_joint_bound=optimized,
                use_pickup_bound=optimized,
            )
        out.update(status=boundary["status"], suffix_search=boundary, best=boundary["best"])
        for key in (
            "latest_repair_delay_seconds",
            "verified_feasible_lower_seconds",
            "proven_infeasible_upper_seconds",
        ):
            value = boundary[key]
            out[key] = None if value is None else offset + value
        if mode == "boundary" and out["status"] == "FINITE" and remaining() > 0:
            witness = boundary["best"]
            opt = solve_recovery(
                problem,
                boundary["latest_repair_delay_seconds"],
                options(),
                warm_schedule=witness["schedule"] if optimized else None,
            )
            out["optimization"] = opt.metadata
            if opt.feasible and opt.metadata["makespan_seconds"] <= witness["makespan_seconds"]:
                out["best"] = opt.summary()
    best = out.get("best")
    if best and best.get("verification"):
        out["verification_valid"] = best["verification"]["valid"]
        out["makespan_seconds"] = offset + best["makespan_seconds"]
        out["makespan_optimal"] = best["makespan_optimal"]
        out["witness_repair_delay_seconds"] = (
            repair if mode == "solve" else offset + best["repair_delay_seconds"]
        )
        # Replay once more end-to-end, with every original wafer present and
        # the actual interlock active until the requested absolute repair time.
        sim = incident.at_fault()
        r = out["witness_repair_delay_seconds"]
        if r > 0:
            sim.state.chambers[incident.failed_chamber].available = False
            sim._queue("ChamberAvailable", prefix["fault_time"] + r, source=incident.failed_chamber)
        sim.run_until(prefix["dispatch_time"])
        for decision in best["verification"]["decisions"]:
            sim.run_until(decision["time"])
            action = Action(**decision["action"])
            if (
                incident.policy == "sealed_finished"
                and action.kind == "pick"
                and action.source == incident.failed_chamber
                and not sim.state.chambers[incident.failed_chamber].available
            ):
                raise RuntimeError("End-to-end interlock rejected early extraction")
            if not sim.submit(action):
                raise RuntimeError("End-to-end simulator rejected scheduled action")
        sim.run_until(prefix["fault_time"] + out["makespan_seconds"])
        checks(sim.trace, incident.residency, incident.holding)
        if not sim.completed or not sim.validate_state():
            raise RuntimeError("End-to-end replay did not complete all WIP")
        out["completed_at"] = {wid: w.completed_at for wid, w in sim.state.wafers.items()}
        out["executed_events"] = [
            {k: e[k] for k in ("time", "event", "wafer_id", "source", "destination")}
            for e in sim.trace
            if e["time"] >= prefix["fault_time"]
        ]
    out["elapsed_seconds"] = perf_counter() - started
    return out
