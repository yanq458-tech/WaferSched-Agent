"""Offline demo, custom state solving, certification and reproducible benchmark."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from ..cpsat_solver import SolverOptions
from .artifacts import plot_schedule, save_query, write_json
from .boundary import repair_boundary
from .examples import terminal_competition
from .solver import solve_recovery
from .state import RecoveryProblem


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("demo", "solve", "boundary", "agent", "benchmark"), nargs="?", default="demo")
    parser.add_argument("--input", type=Path, help="RecoveryProblem schema JSON; default is the 3-wafer example")
    parser.add_argument("--repair", type=float, default=12, help="Seconds AFTER snapshot/fault time")
    parser.add_argument("--output", type=Path, help="Must be a NEW directory")
    parser.add_argument("--seconds", type=float, default=5, help="Maximum solver seconds per query")
    parser.add_argument("--total-seconds", type=float, default=60)
    parser.add_argument("--joint", action="store_true", help="Enable proved subclass pruning")
    args = parser.parse_args(argv)
    root = args.output or Path("results/recovery") / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    if args.command == "benchmark":
        from .experiments import run_benchmark
        summary = run_benchmark(root, per_query_seconds=args.seconds, total_seconds=args.total_seconds)
        print(json.dumps({"output": str(root.resolve()), **summary}, ensure_ascii=False, indent=2))
        return 0 if summary["resolved_runs"] == summary["method_runs"] and not summary["verification_failures"] else 2
    problem = (RecoveryProblem.from_dict(json.loads(args.input.read_text(encoding="utf-8")))
               if args.input else terminal_competition())
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "input.json", problem.to_dict())
    options = SolverOptions(max_seconds=args.seconds)
    def capture(i, r):
        save_query(root / "queries", i, r)
    if args.command == "solve":
        result = solve_recovery(problem, args.repair, options, use_joint_bound=args.joint)
        capture(0, result)
        summary = result.summary()
        plot_schedule(result, root / "schedule.png")
    elif args.command == "boundary":
        summary = repair_boundary(problem, options, total_seconds=args.total_seconds,
                                  use_joint_bound=args.joint, on_query=capture)
    else:
        from .agent import run_recovery_agent
        summary = run_recovery_agent(problem, total_seconds=args.total_seconds,
            max_query_seconds=args.seconds, initial_seconds=min(.05, args.seconds), on_query=capture)
        if args.command == "demo" and summary["status"] == "FINITE":
            result = solve_recovery(problem, summary["latest_repair_delay_seconds"], options)
            save_query(root / "demo_schedule", 0, result)
            plot_schedule(result, root / "schedule.png")
    write_json(root / "result.json", summary)
    print(json.dumps({"status": summary["status"], "rho_seconds": summary.get("latest_repair_delay_seconds"),
                      "output": str(root.resolve())}, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"FINITE", "UNBOUNDED", "INFEASIBLE_AT_ZERO", "OPTIMAL", "FEASIBLE", "INFEASIBLE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
