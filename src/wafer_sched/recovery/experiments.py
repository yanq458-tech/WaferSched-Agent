"""Frozen offline benchmark with independent oracle and real per-call evidence."""

import csv
from pathlib import Path
from time import perf_counter

from ..cpsat_solver import SolverOptions
from .agent import run_recovery_agent
from .artifacts import plot_comparison, save_query, write_json
from .boundary import repair_boundary
from .bounds import symmetric_formula
from .enumeration import enumerate_terminal
from .examples import terminal_competition
from .solver import solve_recovery


CASES = {
    "symmetric_2": dict(m=1, deadline=3, processing=3),
    "symmetric_3": dict(m=2, deadline=6, processing=10),
    "competition_4": dict(m=3, deadline=7, processing=9, residency=2),
    "heterogeneous_p": dict(m=1, deadlines=[4,5], process_times=[6,8], residencies=[1,2]),
    "heterogeneous_delta": dict(m=2, deadlines=[6,6,6], process_times=[6,9,7], residencies=[1,3,2]),
    "unbounded_bypass": dict(m=1, count=1, deadline=2, processing=3),
    "unbounded_mandatory": dict(m=0, count=1, deadline=2, processing=3),
    "immediate_infeasible": dict(m=1, deadline=0, processing=3),
    "fractional": dict(m=1, deadline=5.5, processing=6.25, residency=1.25),
}


def run_benchmark(directory, *, per_query_seconds=5, total_seconds=60):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "manifest.json", {"schema_version": 1, "cases": CASES,
        "per_query_seconds": per_query_seconds, "total_seconds_per_method": total_seconds,
        "seed": 0, "workers": 1, "repetitions": 1,
        "comparison": "same warm-state exact model; joint-safe-pruning; offline feedback orchestration",
        "original_static_CP_SAT": "UNSUPPORTED: requires empty initial state, no fault/residency; not run as a false baseline",
        "PPO": "UNSUPPORTED: existing environment excludes faults; weights not loaded or trained",
        "cost": "offline API cost zero; CPU wall time measured; money/energy not estimated"})
    rows, oracle_rows = [], []
    for name, parameters in CASES.items():
        problem = terminal_competition(**parameters)
        case_root = root / name
        write_json(case_root / "input.json", problem.to_dict())
        case_results = []
        for method in ("cp_sat_recovery", "joint_exact", "offline_agent"):
            method_root = case_root / method
            records = []
            def capture(index, result):
                records.append(result.metadata)
                save_query(method_root, index, result)
            started = perf_counter()
            options = SolverOptions(max_seconds=per_query_seconds)
            result = (run_recovery_agent(problem, total_seconds=total_seconds,
                      max_query_seconds=per_query_seconds, on_query=capture) if method == "offline_agent"
                      else repair_boundary(problem, options, total_seconds=total_seconds,
                      use_joint_bound=method == "joint_exact", on_query=capture))
            # Compare makespan at the certified boundary; for infinity use fixed r=0.
            # This postcheck has a separate disclosed per-query budget for all methods.
            span, verified, delay, span_optimal = None, None, None, None
            if result["status"] in {"FINITE", "UNBOUNDED"}:
                delay = result["latest_repair_delay_seconds"] if result["status"] == "FINITE" else 0
                check = solve_recovery(problem, delay, options, use_joint_bound=method != "cp_sat_recovery")
                capture(len(records), check)
                verified = check.feasible
                span = check.metadata["makespan_seconds"] if check.feasible else None
                span_optimal = check.metadata.get("makespan_optimal", False)
                write_json(method_root / "makespan_check.json", check.summary())
            write_json(method_root / "boundary.json", result)
            feasible_queries = [r for r in records if r["status"] in {"OPTIMAL", "FEASIBLE"}]
            row = {"scenario": name, "method": method, "status": result["status"],
                "rho_seconds": result["latest_repair_delay_seconds"], "makespan_seconds": span,
                "makespan_optimal": span_optimal,
                "makespan_query_repair_seconds": delay if span is not None else None,
                "verified": verified, "total_seconds": perf_counter()-started,
                "solver_seconds": sum(r["solver_seconds"] for r in records),
                "branches": sum(r["branches"] for r in records),
                "conflicts": sum(r["conflicts"] for r in records),
                "query_count": len(records), "unknown_queries": sum(r["status"] == "UNKNOWN" for r in records),
                "feasible_queries": len(feasible_queries),
                "verification_failures": sum(r["status"] == "VERIFICATION_FAILED" for r in records),
                "symmetric_formula": symmetric_formula(problem)}
            rows.append(row)
            case_results.append(result)
        known = [(r["status"], r["latest_repair_delay_seconds"]) for r in case_results if r["status"] != "UNKNOWN"]
        if len(set(known)) > 1:
            raise RuntimeError(f"Algorithm disagreement in {name}: {known}")
        # Small finite cases: check all integer repairs through the first infeasible tick.
        finite = next((r for r in case_results if r["status"] == "FINITE"), None)
        if finite and len(problem.config.wafers) <= 3 and problem.scale == 1:
            rho = int(finite["latest_repair_delay_seconds"])
            for delay in range(rho+2):
                oracle = enumerate_terminal(problem, delay)
                expected = "FEASIBLE" if delay <= rho else "INFEASIBLE"
                oracle_rows.append({"scenario": name, "repair_delay": delay, "expected": expected, **oracle})
                if oracle["status"] != expected:
                    raise RuntimeError(f"Independent oracle disagreement in {name}, r={delay}")
    stress = terminal_competition()
    for label, kwargs in (("unknown_retry", {"initial_seconds": 0}),
                          ("budget_exhausted", {"initial_seconds": 1, "max_rounds": 1})):
        result = run_recovery_agent(stress, **kwargs,
            on_query=lambda i, r, label=label: save_query(root / label, i, r))
        write_json(root / label / "agent.json", result)
    write_json(root / "results.json", rows)
    write_json(root / "independent_enumeration.json", oracle_rows)
    with (root / "results.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    plot_comparison(rows, root)
    summary = {"scenario_count": len(CASES), "method_runs": len(rows),
        "resolved_runs": sum(r["status"] != "UNKNOWN" for r in rows),
        "verification_failures": sum(r["verification_failures"] for r in rows),
        "feasible_queries": sum(r["feasible_queries"] for r in rows),
        "unknown_queries": sum(r["unknown_queries"] for r in rows),
        "total_queries": sum(r["query_count"] for r in rows),
        "independent_enumeration_queries": len(oracle_rows),
        "boundary_agreement": True, "api_calls": 0,
        "resolved_run_fraction": sum(r["status"] != "UNKNOWN" for r in rows)/len(rows),
        "unknown_query_fraction": sum(r["unknown_queries"] for r in rows)/sum(r["query_count"] for r in rows),
        "verified_postchecks": sum(r["verified"] is True for r in rows),
        "replay_valid_fraction": (sum(r["feasible_queries"] for r in rows) /
            max(1, sum(r["feasible_queries"]+r["verification_failures"] for r in rows))),
        "limitations": "One repetition, synthetic fixtures; wall-time differences are not a statistical superiority claim"}
    write_json(root / "summary.json", summary)
    return summary
