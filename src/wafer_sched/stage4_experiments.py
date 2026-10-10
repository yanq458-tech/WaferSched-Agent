"""Six-algorithm static comparisons; solver status and physical validity separate."""

import argparse
from dataclasses import replace
import csv
import gzip
import io
import json
from pathlib import Path
from time import perf_counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from wafer_sched.infrastructure.io import atomic_record

from .artifacts import PROJECT_ROOT, _atomic_bytes, _atomic_text, save_run
from .cpsat_solver import SolverOptions, solve_schedule
from .cpsat_validator import validate_solution
from .metrics import calculate_metrics
from .policies.rules import POLICIES, make_policy
from .policy_runner import run_policy
from .reporting import plot_gantt
from .simulator import Simulator
from .stage4_metrics import proof_comparison
from .stage4_scenarios import load_suite


def dump_decisions(directory, decisions):
    _atomic_bytes(directory / "decisions.json.gz", gzip.compress(json.dumps(
        decisions, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))


def base_row(row, name, simulator, outcome, elapsed):
    metrics = calculate_metrics(simulator.trace)
    complete = outcome["status"] == "completed"
    return {"scenario": row["scenario"], "group": row["group"], "size_class": row["size_class"],
            "policy": name, "wafer_count": len(simulator.config.wafers),
            "chamber_count": len(simulator.config.chambers),
            "process_count": sum(len(wafer.route) for wafer in simulator.config.wafers),
            "seed": simulator.seed, "status": outcome["status"],
            "window_seconds": metrics["window_duration_seconds"],
            "makespan_seconds": metrics["makespan_seconds"] if complete else None,
            "wph": metrics["finite_batch_wph"],
            "completion_batch_wph": metrics["completed_wafers"] * 3600 / metrics["makespan_seconds"] if complete else None,
            "mean_chamber_utilization": metrics["mean_chamber_utilization"],
            "robot_utilization": metrics["robot_utilization"], "average_waiting_seconds": metrics["average_waiting_seconds"],
            "blocking_seconds": metrics["blocking_seconds"], "completed_wafers": metrics["completed_wafers"],
            "constraint_violations": outcome.get("constraint_violations", 0),
            "deadlock_count": int(outcome["status"] == "deadlocked"), "algorithm_runtime_seconds": elapsed,
            "cp_sat_status": "NOT_APPLICABLE", "best_bound_seconds": None, "optimality_gap": None,
            "cp_build_seconds": None, "cp_solver_seconds": None, "validated": bool(simulator.validate_state()) and complete,
            "run_directory": f"{row['scenario']}-{name}-s{simulator.seed}"}


def plots(root):
    with (root / "comparison.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    scenarios = list(dict.fromkeys(row["scenario"] for row in rows))
    policies = [*POLICIES, "cpsat"]
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), layout="constrained")
    for ax, names in zip(axes, (scenarios[:8], scenarios[8:])):
        for index, policy in enumerate(policies):
            values = [next(row["makespan_seconds"] for row in rows if row["scenario"] == name and row["policy"] == policy)
                      for name in names]
            ax.bar([position + (index - 2.5) * .12 for position in range(len(names))],
                   [float(value) if value else float("nan") for value in values], width=.115, label=policy)
        ax.set(xticks=range(len(names)), xticklabels=names, ylabel="Makespan (seconds)")
        ax.grid(axis="y", alpha=.2)
        ax.legend(ncol=6, fontsize=8)
    axes[0].set_title("Original-engine validated schedules; missing bars denote no complete valid schedule")
    fig.savefig(root / "makespan_comparison.png", dpi=150)
    plt.close(fig)
    scale = [row for row in rows if row["policy"] == "cpsat" and row["group"] == "scale"]
    fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
    for i, row in enumerate(scale):
        ax.bar(i, float(row["cp_build_seconds"]), label="model build" if i == 0 else None, color="#54a24b")
        ax.bar(i, float(row["cp_solver_seconds"]), bottom=float(row["cp_build_seconds"]),
               label="solver" if i == 0 else None, color="#2878b5")
        ax.text(i, float(row["cp_build_seconds"]) + float(row["cp_solver_seconds"]),
                row["cp_sat_status"], ha="center", va="bottom", fontsize=9)
    ax.set(xticks=range(len(scale)), xticklabels=[f"{row['scenario']}\nN={row['wafer_count']} C={row['chamber_count']} ops={row['process_count']}" for row in scale],
           ylabel="Wall-clock seconds", title="One-thread search under declared time limits")
    ax.legend()
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
    fig.savefig(root / "scale_runtime.png", dpi=150)
    plt.close(fig)


def run_stage4(root, *, suite_path=None, seed=None, workers=None, max_seconds=None):
    suite = load_suite(suite_path)
    seed = suite["seed"] if seed is None else seed
    workers = suite["workers"] if workers is None else workers
    root.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "status": "running", "seed": seed, "workers": workers,
                "seed_semantics": "deterministic_equipment_solver_search_seed_not_independent_environment_samples",
                "instances": [{**{key: value for key, value in row.items() if key != "equipment"},
                               "equipment": row["equipment"].to_dict()} for row in suite["scenarios"]]}
    atomic_record(root / "manifest.json", manifest)
    comparison, inconsistencies, proof = [], [], []
    for row in suite["scenarios"]:
        config, scenario = row["equipment"], row["scenario"]
        rule_rows, incumbents = [], []
        # The five unchanged baseline implementations run afresh, never overwrite stage3.
        for name in POLICIES:
            simulator = Simulator(config, seed=seed)
            run = run_policy(simulator, make_policy(name), max_time=row["window_seconds"])
            if run.outcome["status"] == "completed":
                incumbents.append(simulator)
            simulator.run_until(row["window_seconds"])
            directory = save_run(simulator, run.outcome, run_id=f"{scenario}-{name}-s{seed}",
                                 output_root=root, compress_events=True)
            dump_decisions(directory, run.decisions)
            if run.outcome["status"] == "completed":
                plot_gantt(directory, f"stage4 {scenario} / {name}")
            rule_rows.append(base_row(row, name, simulator, run.outcome, run.outcome["policy_execution_seconds"]))
        best = min(incumbents, key=lambda sim: max(w.completed_at for w in sim.state.wafers.values()), default=None)
        options = SolverOptions(**{**row.get("solver_options", {}),
                                   "max_seconds": row["solver_seconds"] if max_seconds is None else max_seconds,
                                   "seed": seed, "workers": workers})
        result = solve_schedule(config, options, incumbent=best)
        started = perf_counter()
        replay, validation = validate_solution(config, result, seed=seed)
        replay_seconds = perf_counter() - started
        verified = validation["valid"]
        if replay is not None:
            simulator = replay.simulator
            outcome = {"status": "completed" if verified else "validation_failed", "driver": "schedule_adapter",
                       "constraint_violations": replay.report["constraint_violations"], "policy": "cpsat"}
            if simulator.state.time <= row["window_seconds"]:
                simulator.run_until(row["window_seconds"])
        else:
            simulator = Simulator(config, seed=seed)
            outcome = {"status": "no_solver_schedule", "driver": "schedule_adapter", "constraint_violations": 0, "policy": "cpsat"}
            # No invented rollout or metrics when no CP schedule exists.
        directory = save_run(simulator, outcome, run_id=f"{scenario}-cpsat-s{seed}", output_root=root, compress_events=True)
        atomic_record(directory / "solver.json", result.metadata)
        atomic_record(directory / "schedule.json", result.schedule)
        atomic_record(directory / "validation.json", validation)
        _atomic_text(directory / "solver.txt", result.log)
        dump_decisions(directory, replay.decisions if replay is not None else [])
        if verified:
            plot_gantt(directory, f"stage4 {scenario} / CP-SAT {result.metadata['status']}")
        elif result.schedule is not None:
            inconsistencies.append({"scenario": scenario, "solver": result.metadata, "validation": validation})
        cp_row = base_row(row, "cpsat", simulator, outcome, result.metadata["total_seconds"])
        if result.schedule is None:
            for field in ("wph", "completion_batch_wph", "mean_chamber_utilization", "robot_utilization",
                          "average_waiting_seconds", "blocking_seconds", "completed_wafers", "window_seconds"):
                cp_row[field] = None
        cp_row.update(cp_sat_status=result.metadata["status"], best_bound_seconds=result.metadata["best_bound_seconds"],
                      optimality_gap=result.metadata["relative_gap"], cp_build_seconds=result.metadata["build_seconds"],
                      cp_solver_seconds=result.metadata["solver_seconds"], replay_seconds=replay_seconds)
        for item in [*rule_rows, cp_row]:
            item.update(proof_comparison(item["makespan_seconds"], result.metadata, verified),
                        reference_cp_status=result.metadata["status"], reference_cp_best_bound_seconds=result.metadata["best_bound_seconds"])
            comparison.append(item)
        proof.append({"scenario": scenario, **result.metadata, "replay_valid": verified})
        print(f"{scenario}: {result.metadata['status']} CP={result.metadata['objective_seconds']} "
              f"bound={result.metadata['best_bound_seconds']} gap={result.metadata['relative_gap']} "
              f"replay={verified} solver={result.metadata['solver_seconds']:.3f}s", flush=True)
    fields = list(dict.fromkeys(key for row in comparison for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(comparison)
    _atomic_text(root / "comparison.csv", stream.getvalue())
    atomic_record(root / "solver_proofs.json", proof)
    atomic_record(root / "model_inconsistencies.json", {"replay_mismatches": inconsistencies,
                  "unsupported": ["downtime_pause_recovery", "arbitrary_midrun_initial_state", "zero_pick_or_place", "unannounced_future_arrivals_online", "nonrepresentable_tick_times"]})
    diagnostics(root, suite["scenarios"][0]["equipment"])
    plots(root)
    manifest.update(status="completed" if not inconsistencies else "completed_with_validation_failures",
                    instance_count=len(suite["scenarios"]), algorithm_run_count=len(comparison))
    atomic_record(root / "manifest.json", manifest)
    return comparison


def diagnostics(root, original):
    """Real negative solver/replay cases, separated from fair comparisons."""
    from copy import deepcopy

    config = replace(original, wafers=original.wafers[:1])
    records = []
    for name, options in (("restricted_horizon", SolverOptions(horizon_seconds=5)),
                          ("zero_time_limit", SolverOptions(max_seconds=0))):
        result = solve_schedule(config, options)
        atomic_record(root / f"diagnostic_{name}.json", result.metadata)
        _atomic_text(root / f"diagnostic_{name}.txt", result.log)
        records.append({"case": name, "status": result.metadata["status"], "schedule_available": result.schedule is not None})
    result = solve_schedule(config, SolverOptions())
    if result.schedule:
        corrupted = deepcopy(result)
        corrupted.schedule["processes"][0]["end_tick"] += 1
        _, report = validate_solution(config, corrupted)
        atomic_record(root / "diagnostic_tampered_prediction.json", report)
        records.append({"case": "tampered_prediction", "valid": report["valid"], "issues": report["issues"]})
    atomic_record(root / "negative_cases.json", records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results/wafer_sched/stage4")
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--max-seconds", type=float)
    args = parser.parse_args()
    run_stage4(args.output, suite_path=args.suite, seed=args.seed, workers=args.workers, max_seconds=args.max_seconds)


if __name__ == "__main__":
    main()
