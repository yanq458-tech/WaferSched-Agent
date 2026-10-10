"""Frozen validation-selected policies, unchanged rules and verified CP references."""

import argparse
import csv
import gzip
import io
import json
from pathlib import Path

import numpy as np
import torch

from wafer_sched.infrastructure.io import atomic_record
from ..actions import Action
from ..artifacts import PROJECT_ROOT, _atomic_bytes, _atomic_text, save_run
from ..config import load_config
from ..cpsat_solver import SolveResult, SolverOptions, solve_schedule
from ..cpsat_validator import validate_solution
from ..metrics import calculate_metrics
from ..observation import Observation, freeze
from ..policies.rules import POLICIES, make_policy
from ..policy_runner import run_policy
from ..reporting import plot_gantt
from ..simulator import Simulator
from ..stage4_metrics import proof_comparison
from .encoding import ActionEncoder, EncodingSchema
from .policy import TrainedPolicyAdapter
from .training import make_env, masked_episode


def dump_json_gz(path, payload):
    _atomic_bytes(path, gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0))


def audit_mask_against_checker(simulator, observation, encoder):
    """Enumerate independently, including physically invalid wafer/destination pairs."""
    legal = simulator.legal_actions()
    mask = encoder.mask(observation, legal)
    actual = np.zeros(encoder.schema.action_count, dtype=bool)
    actual[0] = bool(simulator.validate_action(Action.wait()))
    wafers, chambers = sorted(observation.wafers), sorted(observation.chambers)
    for w, wafer in enumerate(wafers):
        for d, destination in enumerate(chambers):
            actual[1 + w * (encoder.schema.max_chambers + 1) + d] = bool(
                simulator.validate_action(Action.transfer(wafer, destination)))
        actual[1 + w * (encoder.schema.max_chambers + 1) + encoder.schema.max_chambers] = bool(
            simulator.validate_action(Action.unload(wafer)))
    return {"checked_indices": len(mask), "false_positive": int(np.sum(mask & ~actual)),
            "false_negative": int(np.sum(~mask & actual)), "legal_count": int(mask.sum())}


def verify_decision_masks(config, decisions, schema):
    sim = Simulator(config)
    totals = {"decisions": 0, "checked_indices": 0, "false_positive": 0, "false_negative": 0,
              "selected_masked_out": 0}
    encoder = ActionEncoder(schema)
    for decision in decisions:
        sim.run_until(decision["time"])
        view = decision["observation"]
        observation = Observation(decision["time"], freeze(view["robot"]), freeze(view["chambers"]),
                                  freeze(view["wafers"]), freeze(view["history"]), view["completed_count"])
        audit = audit_mask_against_checker(sim, observation, encoder)
        totals["decisions"] += 1
        for key in ("checked_indices", "false_positive", "false_negative"):
            totals[key] += audit[key]
        action = Action(**decision["action"])
        index = encoder.index(action, observation)
        totals["selected_masked_out"] += int(not encoder.mask(observation, sim.legal_actions())[index])
        if action.kind != "wait":
            result = sim.submit(action)
            if not result:
                raise RuntimeError(f"Saved decision failed original replay: {result}")
        # The next saved time drives event advancement, including automatic busy/wait events.
    if totals["false_positive"] or totals["false_negative"] or totals["selected_masked_out"]:
        raise RuntimeError(f"Mask/checker mismatch: {totals}")
    return totals


def metric_row(scenario, simulator, outcome, *, policy, seed=None, inference_seconds=None):
    metrics = calculate_metrics(simulator.trace)
    span = metrics["makespan_seconds"]
    return {"scenario": scenario["name"], "training_group": scenario["training_group"], "split": scenario["split"],
            "policy": policy, "training_seed": seed, "environment_seed": simulator.seed,
            "status": outcome["status"], "window_seconds": metrics["window_duration_seconds"],
            "makespan_seconds": span, "wph": metrics["finite_batch_wph"],
            "completion_batch_wph": metrics["completed_wafers"] * 3600 / span if span else None,
            "mean_chamber_utilization": metrics["mean_chamber_utilization"],
            "robot_utilization": metrics["robot_utilization"],
            "average_waiting_seconds": metrics["average_waiting_seconds"], "blocking_seconds": metrics["blocking_seconds"],
            "completed_wafers": metrics["completed_wafers"], "wafer_count": len(simulator.config.wafers),
            "completion_rate": metrics["completed_wafers"] / len(simulator.config.wafers),
            "inference_seconds": inference_seconds, "constraint_violations": outcome.get("constraint_violations", 0),
            "deadlock_count": int(outcome["status"] == "deadlocked")}


class RLEvaluationRunner:
    def run(self, suite_path, training_root, output_root):
        suite = json.loads(Path(suite_path).read_text(encoding="utf-8"))
        schema = EncodingSchema(**suite["schema"])
        training_root, output_root = Path(training_root), Path(output_root)
        output_root.mkdir(parents=True, exist_ok=False)
        torch.set_num_threads(1)
        atomic_record(output_root / "evaluation_config.json", suite)
        models, specifications = {}, {}
        for group in {row["training_group"] for row in suite["scenarios"]}:
            specifications[group] = json.loads((training_root / group / "training_config.json").read_text(encoding="utf-8"))
            frozen_suite = json.loads((training_root / group / "evaluation_suite_before_training.json").read_text(encoding="utf-8"))
            if suite != frozen_suite:
                raise ValueError("Test suite changed after training started")
            for seed in suite["training_seeds"]:
                path = training_root / group / f"seed-{seed}/models/best.zip"
                models[group, seed] = TrainedPolicyAdapter.load(path)
                if models[group, seed].schema != schema:
                    raise ValueError("Cross-scenario encoding schema mismatch")
        rows, mask_audits = [], []
        manifest = {"status": "running", "prediction": "deterministic_masked",
                    "seed_semantics": "three_training_replicates_single_deterministic_environment_seed",
                    "historical_cp_references": [], "runs": []}
        atomic_record(output_root / "manifest.json", manifest)
        for scenario in suite["scenarios"]:
            config = load_config(PROJECT_ROOT / scenario["config"])
            window, name = scenario["window_seconds"], scenario["name"]
            instances, local_rows = [], []
            for policy_name in POLICIES:
                sim = Simulator(config, seed=suite["environment_seed"])
                run = run_policy(sim, make_policy(policy_name), max_time=window)
                if run.outcome["status"] == "completed":
                    instances.append(sim)
                sim.run_until(window)
                directory = save_run(sim, run.outcome, run_id=f"{name}-{policy_name}", output_root=output_root, compress_events=True)
                dump_json_gz(directory / "decisions.json.gz", run.decisions)
                local_rows.append({**metric_row(scenario, sim, run.outcome, policy=policy_name,
                                               inference_seconds=run.outcome["policy_execution_seconds"]),
                                   "run_directory": directory.name})
            reference = scenario["stage4_reference"]
            if reference:
                directory = PROJECT_ROOT / f"results/wafer_sched/stage4/{reference}-cpsat-s0"
                if not directory.is_dir():
                    # Human-readable suite aliases can differ from stored instance names.
                    # Resolve only via the exact original config name, then check all data.
                    directory = PROJECT_ROOT / f"results/wafer_sched/stage4/{config.name}-cpsat-s0"
                if json.loads((directory / "config.json").read_text(encoding="utf-8")) != config.to_dict():
                    raise ValueError("Historical CP comparison configuration mismatch")
                result = SolveResult(json.loads((directory / "solver.json").read_text(encoding="utf-8")),
                                     json.loads((directory / "schedule.json").read_text(encoding="utf-8")),
                                     (directory / "solver.txt").read_text(encoding="utf-8"))
                manifest["historical_cp_references"].append(directory.relative_to(PROJECT_ROOT).as_posix())
            else:
                best = min(instances, key=lambda sim: calculate_metrics(sim.trace)["makespan_seconds"], default=None)
                result = solve_schedule(config, SolverOptions(max_seconds=scenario["solver_seconds"],
                                                               workers=1, seed=suite["environment_seed"]), incumbent=best)
            replay, validation = validate_solution(config, result, seed=suite["environment_seed"])
            cp_sim = replay.simulator if replay is not None else Simulator(config, seed=suite["environment_seed"])
            if replay is not None and not validation["valid"]:
                raise RuntimeError(f"CP reference failed original replay: {validation}")
            cp_outcome = {"status": "completed" if validation["valid"] else "no_solver_schedule", "policy": "cpsat",
                          "driver": "schedule_adapter", "constraint_violations": 0}
            if validation["valid"]:
                cp_sim.run_until(window)
            cp_directory = save_run(cp_sim, cp_outcome, run_id=f"{name}-cpsat", output_root=output_root, compress_events=True)
            for filename, value in (("solver.json", result.metadata), ("schedule.json", result.schedule), ("validation.json", validation)):
                atomic_record(cp_directory / filename, value)
            _atomic_text(cp_directory / "solver.txt", result.log)
            cp_row = {**metric_row(scenario, cp_sim, cp_outcome, policy="cpsat"),
                      "run_directory": cp_directory.name}
            if not validation["valid"]:
                for key in ("makespan_seconds", "wph", "completion_batch_wph", "mean_chamber_utilization",
                            "robot_utilization", "average_waiting_seconds", "blocking_seconds", "completion_rate"):
                    cp_row[key] = None
            local_rows.append(cp_row)
            for seed in suite["training_seeds"]:
                adapter = models[scenario["training_group"], seed]
                sim = Simulator(config, seed=suite["environment_seed"])
                run = run_policy(sim, adapter, max_time=window)
                # Independently execute Gym steps with explicit predict(..., action_masks=...).
                env = make_env(config, specifications[scenario["training_group"]], max_time=window)
                summary = masked_episode(adapter.model, env, seed=suite["environment_seed"])
                env.simulator.run_until(window)
                sim.run_until(window)
                if sim.trace != env.simulator.trace:
                    raise RuntimeError("Gym stepping and existing Policy runner generated different physical events")
                mask_audit = verify_decision_masks(config, run.decisions, schema)
                mask_audits.append({"scenario": name, "training_seed": seed, **mask_audit})
                directory = save_run(sim, {**run.outcome, "training_seed": seed, "driver": "policy_runner",
                                           "gym_trace_equal": True}, run_id=f"{name}-maskable_ppo-s{seed}",
                                     output_root=output_root, compress_events=True)
                dump_json_gz(directory / "decisions.json.gz", run.decisions)
                dump_json_gz(directory / "gym_decisions.json.gz", env.episode_decisions)
                atomic_record(directory / "episode_summary.json", summary)
                atomic_record(directory / "mask_audit.json", mask_audit)
                if run.outcome["status"] == "completed":
                    plot_gantt(directory, f"stage5 {name} / MaskablePPO training seed {seed}")
                local_rows.append({**metric_row(scenario, sim, run.outcome, policy="maskable_ppo", seed=seed,
                                               inference_seconds=run.outcome["policy_execution_seconds"]),
                                   "run_directory": directory.name})
                env.close()
            for row in local_rows:
                row.update(cp_sat_status=result.metadata["status"], cp_reference_reused=bool(reference),
                           cp_reference_runtime_seconds=result.metadata["total_seconds"],
                           cp_best_bound_seconds=result.metadata["best_bound_seconds"],
                           cp_incumbent_seconds=result.metadata["objective_seconds"] if validation["valid"] else None,
                           **proof_comparison(row["makespan_seconds"], result.metadata, validation["valid"]))
                rows.append(row)
                manifest["runs"].append({"scenario": name, "policy": row["policy"], "training_seed": row["training_seed"],
                                         "status": row["status"], "makespan_seconds": row["makespan_seconds"]})
            print(f"Evaluated {name}: " + ", ".join(f"{r['policy']}({r['training_seed']})={r['makespan_seconds']}" for r in local_rows), flush=True)
            atomic_record(output_root / "manifest.json", manifest)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        _atomic_text(output_root / "comparison.csv", stream.getvalue())
        atomic_record(output_root / "mask_statistics.json", mask_audits)
        manifest.update(status="completed", run_count=len(rows), gym_policy_trace_comparisons=len(mask_audits))
        atomic_record(output_root / "manifest.json", manifest)
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=PROJECT_ROOT / "configs/wafer_sched/rl/evaluation_suite.json")
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    RLEvaluationRunner().run(args.suite, args.training_root, args.output)


if __name__ == "__main__":
    main()
