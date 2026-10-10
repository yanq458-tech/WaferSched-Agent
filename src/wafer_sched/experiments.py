"""Reproducible stage-three study CLI (no solver, training, or LLM)."""

import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from wafer_sched.infrastructure.io import atomic_record

from .artifacts import PROJECT_ROOT, _atomic_bytes, _atomic_text, save_run
from .metrics import calculate_metrics
from .policies.rules import POLICIES, make_policy
from .policy_runner import run_policy
from .reporting import plot_comparisons, plot_gantt
from .scenarios import study_scenarios
from .simulator import Simulator


def run_study(root: Path, *, seeds=(0, 7)):
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Seeds must be nonempty and unique")
    root.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "status": "running", "seeds": list(seeds),
                "seed_semantics": "metadata_only_no_randomness_two_seeds_check_replay_not_statistical_samples",
                "policies": list(POLICIES), "scenarios": []}
    for name, config, window in study_scenarios():
        manifest["scenarios"].append({"name": name, "window_seconds": window,
                                      "equipment": config.to_dict()})
    atomic_record(root / "manifest.json", manifest)
    rows, switch_rows, replay = [], [], {}
    for name, config, window in study_scenarios():
        for seed in seeds:
            for policy_name in POLICIES:
                simulator = Simulator(config, seed=seed)
                run = run_policy(simulator, make_policy(policy_name), max_time=window)
                if run.outcome["status"] != "completed":
                    raise RuntimeError(f"{name}/{policy_name}: {run.outcome}")
                # Close the same declared window for all methods, through real events.
                simulator.run_until(window)
                metrics = calculate_metrics(simulator.trace)
                signature = hashlib.sha256(json.dumps({"events": simulator.trace, "decisions": run.decisions},
                                                       sort_keys=True).encode()).hexdigest()
                key = (name, policy_name)
                if key in replay and replay[key] != signature:
                    raise RuntimeError("Deterministic replay differed across metadata seeds")
                replay[key] = signature
                directory = save_run(simulator, {**run.outcome, "replay_sha256": signature},
                                     run_id=f"{name}-{policy_name}-s{seed}", output_root=root,
                                     compress_events=True)
                _atomic_bytes(directory / "decisions.json.gz", gzip.compress(
                    json.dumps(run.decisions, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
                # Human-readable switches are duplicated in CSV, full scores stay in JSON.
                for decision in run.decisions:
                    explanation = decision["explanation"]
                    if policy_name == "adaptive":
                        switch_rows.append({"scenario": name, "seed": seed, "decision": decision["index"],
                                            "time": decision["time"], "rule": explanation["rule"],
                                            "trigger": explanation["trigger"], "switched": explanation["switched"],
                                            "previous_rule": explanation["switched_from"],
                                            "action": json.dumps(decision["action"], sort_keys=True),
                                            "evidence": json.dumps(explanation["evidence"], sort_keys=True)})
                plot_gantt(directory, f"{name} / {policy_name} / seed {seed}")
                rows.append({"scenario": name, "policy": policy_name, "seed": seed,
                             "window_seconds": window, "makespan_seconds": metrics["makespan_seconds"],
                             "wph": metrics["finite_batch_wph"],
                             "completion_batch_wph": metrics["completed_wafers"] * 3600 / metrics["makespan_seconds"],
                             "mean_chamber_utilization": metrics["mean_chamber_utilization"],
                             "robot_utilization": metrics["robot_utilization"],
                             "average_waiting_seconds": metrics["average_waiting_seconds"],
                             "blocking_seconds": metrics["blocking_seconds"],
                             "completed_wafers": metrics["completed_wafers"],
                             "constraint_violations": run.outcome["constraint_violations"],
                             "policy_execution_seconds": run.outcome["policy_execution_seconds"],
                             "decision_count": run.outcome["decision_count"], "run_directory": directory.name})
                print(f"{name} seed={seed} {policy_name}: makespan={metrics['makespan_seconds']:g}s "
                      f"waiting={metrics['average_waiting_seconds']:.3f}s blocking={metrics['blocking_seconds']:g}s", flush=True)
    for filename, values in (("comparison.csv", rows), ("adaptive_decisions.csv", switch_rows)):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
        _atomic_text(root / filename, stream.getvalue())
    plot_comparisons(root)
    manifest.update(status="completed", run_count=len(rows), replay_verified=True)
    atomic_record(root / "manifest.json", manifest)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results/wafer_sched/stage3")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 7])
    args = parser.parse_args()
    run_study(args.output, seeds=tuple(args.seeds))


if __name__ == "__main__":
    main()
