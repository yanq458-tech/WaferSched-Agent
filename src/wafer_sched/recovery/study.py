"""Executable offline v1.3 study and custom schema-2 recovery CLI."""

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from .artifacts import write_json
from .continuation import Continuation
from .dispatch import dispatch_window, recover
from .incidents import scenarios
from .primitive_oracle import enumerate_incident


def benchmark(root, per_query, total):
    rows, oracles = [], []
    for name, case in scenarios().items():
        directory = root / name
        write_json(directory / "input.json", case.to_dict())
        answers = []
        for method, mode, opt in [
            ("baseline", "boundary", False),
            ("enhanced", "boundary", True),
            ("agent", "agent", True),
        ]:
            start = perf_counter()
            result = recover(case, mode, optimized=opt, per_query=per_query, total=total)
            elapsed = perf_counter() - start
            write_json(directory / (method + ".json"), result)
            search = result.get("suffix_search", {})
            calls = [r.get("result", r) for r in search.get("history", [])]
            if "optimization" in result:
                calls.append(result["optimization"])
            rho = result.get("latest_repair_delay_seconds")
            # Common comparison point for all methods, including infinite boundaries.
            check = None
            if result["status"] in {"FINITE", "UNBOUNDED"}:
                check = recover(
                    case,
                    "solve",
                    repair=rho or 0,
                    optimized=opt,
                    per_query=per_query,
                    total=per_query,
                )
                write_json(directory / (method + "-postcheck.json"), check)
            row = dict(
                case=name,
                method=method,
                status=result["status"],
                rho_seconds=rho,
                makespan_seconds=check.get("makespan_seconds") if check else None,
                verified=check.get("verification_valid") if check else None,
                postcheck_status=check["status"] if check else None,
                wall_seconds=elapsed,
                cp_seconds=sum(r["solver_seconds"] for r in calls),
                branches=sum(r["branches"] for r in calls),
                queries=len(calls),
                unknown_queries=sum(r["status"] == "UNKNOWN" for r in calls),
            )
            if check:
                if check["status"] not in {"OPTIMAL","FEASIBLE","UNKNOWN"}:
                    raise RuntimeError(f"Postcheck contradicts certified boundary: {name}/{method}")
                if check["status"] != "UNKNOWN" and not row["verified"]:
                    raise RuntimeError(f"Invalid postcheck witness: {name}/{method}")
            rows.append(row)
            if row["status"] != "UNKNOWN":
                answers.append((row["status"], rho))
        if len(set(answers)) > 1:
            raise RuntimeError(f"Conflicting certified boundaries for {name}: {answers}")
        if name in {
            "mid_pick",
            "mid_place",
            "dispatch_lag",
            "two",
            "heterogeneous",
            "evacuate",
            "sealed",
            "overload",
            "healthy_processing",
            "mid_move",
        }:
            rho = answers[0][1] if answers else None
            for delay in sorted(
                {0, rho, rho + 1 / case.prepare()[0].scale} if rho is not None else {0, 5}
            ):
                cp = recover(case, "solve", repair=delay, per_query=per_query, total=total)
                oracle = enumerate_incident(case, delay)
                agree = None
                if oracle["status"] != "UNKNOWN" and cp["status"] in {"OPTIMAL","INFEASIBLE"}:
                    agree = oracle["status"] == cp["status"] and oracle.get(
                        "makespan_seconds"
                    ) == cp.get("makespan_seconds")
                oracles.append(
                    dict(case=name, repair=delay, cp=cp["status"], **oracle, agree=agree)
                )
                if agree is False:
                    raise RuntimeError(f"Independent oracle disagrees: {oracles[-1]}")
    with (root / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(root / "enumeration.json", oracles)
    for name, kw in [("budget_exhausted", dict(max_rounds=1)), ("zero_budget", dict(total=0))]:
        write_json(root / (name + ".json"), recover(scenarios()["two"], **kw))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), layout="constrained")
    for ax, field, label in zip(
        axes, ("branches", "wall_seconds"), ("CP branches", "Wall time (s)")
    ):
        for method in ("baseline", "enhanced", "agent"):
            group = [r for r in rows if r["method"] == method and r["status"] != "UNSUPPORTED"]
            ax.plot([r["case"] for r in group], [r[field] for r in group], marker="o", label=method)
        ax.set_ylabel(label)
        ax.tick_params(axis="x", rotation=25)
    axes[0].legend()
    fig.savefig(root / "comparison.png")
    plt.close(fig)
    summary = dict(
        cases=len({r["case"] for r in rows}),
        runs=len(rows),
        oracle_checks=len(oracles),
        oracle_agreements=sum(r["agree"] is True for r in oracles),
        query_seconds=per_query,
        total_seconds_per_method=total,
        postcheck_separate_budget_seconds=per_query,
        workers=1,
        repeats=1,
        queries=sum(r["queries"] for r in rows),
        unknown_queries=sum(r["unknown_queries"] for r in rows),
        verified_postchecks=sum(bool(r["verified"]) for r in rows),
    )
    write_json(root / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=["study", "solve", "boundary", "agent"], nargs="?", default="agent"
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repair", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--total", type=float, default=30)
    parser.add_argument(
        "--elapsed",
        type=float,
        help="Equipment seconds since fault at solver entry; run a post-solve clock check",
    )
    args = parser.parse_args(argv)
    root = args.output or Path("results/local/continuation") / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    if args.mode == "study":
        result = benchmark(root, args.seconds, args.total)
    else:
        case = (
            Continuation.from_dict(json.loads(args.input.read_text(encoding="utf-8-sig")))
            if args.input
            else scenarios()["mid_pick"]
        )
        write_json(root / "input.json", case.to_dict())
        start = perf_counter()
        result = recover(
            case, args.mode, repair=args.repair, per_query=args.seconds, total=args.total
        )
        if args.elapsed is not None:
            result["dispatch_check"] = dispatch_window(
                result, args.elapsed + perf_counter() - start
            )
        write_json(root / "result.json", result)
    print(
        json.dumps(
            {
                "directory": str(root),
                **{k: v for k, v in result.items() if not isinstance(v, (dict, list))},
            }
        )
    )


if __name__ == "__main__":
    main()
