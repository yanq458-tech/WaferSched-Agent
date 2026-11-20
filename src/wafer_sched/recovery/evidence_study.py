"""Offline reproducible study. Run from the project root."""

import argparse
import csv
import hashlib
import json
import platform
import random
import statistics
from collections import Counter
from pathlib import Path
from time import perf_counter

import ortools
from .continuation import Continuation
from .direct import direct
from .dispatch import recover
from .replay import witness_observer
from .study_data import SOURCE, corpus
from .study_policy import adaptive

METHODS = ("binary", "direct", "plain_policy", "graph_policy")
ROOT = Path("results/recovery/evidence-study")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Source tree preserves artifact bytes; use identical newlines across operating systems.
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8", newline="\r\n")


def generate(root):
    index = []
    for name, family, seed, case in corpus("data/recovery-study/fractional-seed.json"):
        p, prefix = case.prepare()
        data = case.to_dict()
        path = root / "inputs" / f"{name}.json"
        save(path, data)
        transfers = sum(
            len(w.route)
            - p.snapshot["wafers"][w.wafer_id]["stage"]
            + 1
            - int(
                p.snapshot["wafers"][w.wafer_id]["location"] in p.snapshot["chambers"]
                and p.snapshot["chambers"][p.snapshot["wafers"][w.wafer_id]["location"]]["status"]
                == "processing"
            )
            for w in p.config.wafers
        )
        index.append(
            dict(
                case=name,
                family=family,
                seed=seed,
                wip=len(case.config.wafers),
                remaining_transfers=transfers,
                phase=case.snapshot["robot"]["phase"],
                offset=prefix["offset"],
                source=SOURCE if family == "kim_concurrent_derived" else "project synthetic",
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    save(root / "manifest.json", index)


def run_case(case, method, budget, *, runner=None):
    start = perf_counter()
    times = []
    token = witness_observer.set(lambda: times.append(perf_counter() - start))
    # Identical reserve for serialization-free end-to-end proof/replay overhead.
    allocation = budget * 0.85
    try:
        if runner is not None:
            result = runner(case, method, allocation)
        elif method == "binary":
            result = recover(
                case, "boundary", total=allocation, per_query=allocation, optimized=True
            )
        elif method == "direct":
            result = direct(case, allocation)
        elif method == "graph_legacy":
            result = adaptive(case, allocation, graph=True, try_bypass=False, refined=False)
        elif method == "graph_refined":
            result = adaptive(case, allocation, graph=True, refined=True, ranked=False)
        elif method == "graph_fast":
            result = adaptive(case, allocation, graph=True, fast=True)
        elif method == "graph_ranked":
            result = adaptive(case, allocation, graph=True, refined=True, ranked=True)
        else:
            result = adaptive(case, allocation, graph=method == "graph_policy", refined=False)
    finally:
        witness_observer.reset(token)
    elapsed = perf_counter() - start
    status = result["status"] if elapsed <= budget else "UNKNOWN"
    lower = result.get("verified_feasible_lower_seconds")
    upper = result.get("finite_upper_seconds")
    history = result.get("suffix_search", {})
    if upper is None and result.get("proven_infeasible_upper_seconds") is not None:
        upper = result["proven_infeasible_upper_seconds"] - 1 / history["ticks_per_second"]
    if result["status"] == "FINITE":
        upper = lower = result["latest_repair_delay_seconds"]
    trace = result.get("policy_trace", result.get("trace", history.get("history", [])))
    row = dict(
        method=method,
        budget=budget,
        wall_seconds=elapsed,
        status=status,
        raw_status=result["status"],
        late=elapsed > budget,
        verified=bool(result.get("verification_valid")) and elapsed <= budget,
        first_suffix_witness_seconds=times[0] if times and times[0] <= budget else None,
        rho=result.get("latest_repair_delay_seconds") if elapsed <= budget else None,
        lower=lower if elapsed <= budget else None,
        upper=upper if elapsed <= budget else None,
        gap=upper - lower if elapsed <= budget and None not in (lower, upper) else None,
        makespan=result.get("makespan_seconds") if elapsed <= budget else None,
        makespan_optimal=bool(result.get("makespan_optimal")) and elapsed <= budget,
    )
    evidence = dict(
        trace=trace,
        schedule=(result.get("best") or {}).get("schedule"),
        certificate=result.get("certificate"),
        witness_repair=result.get("witness_repair_delay_seconds"),
        raw_makespan=result.get("makespan_seconds"),
        raw_verified=result.get("verification_valid"),
    )
    return row, evidence


def benchmark(root, budget, selected=None, repeats=1, label="benchmark"):
    index = json.loads((root / "manifest.json").read_text(encoding="utf8"))
    folder = root / label
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    rng = random.Random(458)
    for rep in range(repeats):
        order = index.copy()
        rng.shuffle(order)
        for item in order:
            name = item["case"]
            if selected and name not in selected:
                continue
            path = root / "inputs" / f"{name}.json"
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Snapshot hash mismatch")
            case = Continuation.from_dict(json.loads(path.read_text(encoding="utf8")))
            sequence = list(METHODS)
            rng.shuffle(sequence)
            proved = set()
            for method in sequence:
                row, evidence = run_case(case, method, budget)
                if row["status"] != "UNKNOWN":
                    proved.add((row["status"], row["rho"]))
                if len(proved) > 1:
                    raise RuntimeError(f"Conflicting proofs for {name}: {proved}")
                row.update(case=name, family=item["family"], wip=item["wip"], repeat=rep)
                rows.append(row)
                save(folder / "runs" / f"{name}-{rep}-{method}.json", dict(metrics=row, **evidence))
    with (folder / "results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for method in METHODS:
        data = [r for r in rows if r["method"] == method]
        summary[method] = dict(
            status=dict(Counter(r["status"] for r in data)),
            boundary_proved=sum(
                r["status"] in ("FINITE", "UNBOUNDED", "INFEASIBLE_AT_ZERO") for r in data
            ),
            verified=sum(r["verified"] for r in data),
            late=sum(r["late"] for r in data),
            median_wall_seconds=statistics.median(r["wall_seconds"] for r in data),
        )
    save(
        folder / "summary.json",
        dict(
            budget=budget,
            runs=len(rows),
            repeats=repeats,
            workers=1,
            ortools=ortools.__version__,
            platform=platform.platform(),
            cpu=platform.processor(),
            methods=summary,
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["generate", "benchmark", "validate", "all"])
    parser.add_argument("--out", type=Path, default=ROOT)
    parser.add_argument("--budget", type=float, default=1)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--label", default="benchmark")
    args = parser.parse_args()
    if args.action in ("all", "generate"):
        generate(args.out)
    if args.action in ("all", "validate"):
        from .evidence_validation import validate

        validate(args.out)
    if args.action in ("all", "benchmark"):
        benchmark(args.out, args.budget, args.cases, args.repeats, args.label)


if __name__ == "__main__":
    main()
