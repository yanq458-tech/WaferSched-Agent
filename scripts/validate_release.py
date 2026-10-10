"""Real numerical smoke acceptance. Never train or overwrite historical models."""
# Import guards must be installed before importing the package under audit.
# ruff: noqa: E402
import argparse
import csv
import gzip
import hashlib
import importlib.abc
import json
from pathlib import Path
import sys


class NoRailwayPlatform(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "api" or fullname.startswith("api."):
            raise ImportError("Original platform imports are forbidden in release acceptance")


sys.meta_path.insert(0, NoRailwayPlatform())


def audit_files(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes)):
        value = str(args[0]).replace("\\", "/").lower()
        if "railway_project/" in value:
            raise PermissionError("Original project access is forbidden in numerical acceptance")


sys.addaudithook(audit_files)

from wafer_sched import EquipmentConfig, Simulator, load_config
from wafer_sched.artifacts import save_run
from wafer_sched.driver import run_validation_driver
from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.paths import PROJECT_ROOT, resolve_path
from wafer_sched.metrics import calculate_metrics
from wafer_sched.policy_runner import run_policy


def numerical(output):
    output.mkdir(parents=True, exist_ok=False)
    config = load_config("configs/wafer_sched/minimal_demo.json")
    sim = Simulator(config)
    outcome = run_validation_driver(sim)
    assert outcome["status"] == "completed" and calculate_metrics(sim.trace)["makespan_seconds"] == 47
    save_run(sim, outcome, run_id="demo", output_root=output)
    from wafer_sched.cpsat_solver import SolverOptions, solve_schedule
    from wafer_sched.cpsat_validator import validate_solution
    cp = solve_schedule(config, SolverOptions(max_seconds=3, workers=1, seed=0), incumbent=sim)
    replay, verification = validate_solution(config, cp, seed=0)
    assert verification["valid"] and replay.simulator.completed
    cp_dir = save_run(replay.simulator, {"status": "completed", "driver": "release_cp_replay", "constraint_violations": 0}, run_id="cpsat", output_root=output)
    atomic_record(cp_dir / "solver.json", cp.metadata)
    atomic_record(cp_dir / "schedule.json", cp.schedule)
    atomic_record(cp_dir / "verification.json", verification)
    import torch
    from wafer_sched.rl.policy import TrainedPolicyAdapter
    torch.set_num_threads(1)
    with (PROJECT_ROOT / "results/wafer_sched/stage5/evaluation/comparison.csv").open(encoding="utf-8", newline="") as stream:
        historical_rows = list(csv.DictReader(stream))
    loaded, matched = [], 0
    for index, path in enumerate(sorted((PROJECT_ROOT / "results/wafer_sched/stage5").rglob("*.zip")), 1):
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        metadata = json.loads((path.parent / "metadata.json").read_text(encoding="utf-8"))
        equipment = EquipmentConfig.from_dict(metadata["train_equipment"][0])
        policy = TrainedPolicyAdapter.load(path)
        original = Simulator(equipment, seed=0)
        run = run_policy(original, policy, max_time=1000)
        assert original.completed and run.outcome["constraint_violations"] == 0
        group = metadata["training_group"]
        scenario = "F_competition" if group == "medium" else "S_small"
        reference = next((row for row in historical_rows if row["scenario"] == scenario and
            row["training_seed"] == str(metadata["seed"]) and row["policy"] == "maskable_ppo"), None)
        exact_replay = None
        if path.name == "best.zip" and group in {"small", "medium"}:
            assert reference is not None
            original.run_until(float(reference["window_seconds"]))
            history = PROJECT_ROOT / "results/wafer_sched/stage5/evaluation" / reference["run_directory"]
            raw = json.loads(gzip.decompress((history / "events.json.gz").read_bytes()))["events"]
            assert original.trace == raw
            matched += 1
            exact_replay = True
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        save_run(original, run.outcome, run_id=f"ppo-{index:02d}", output_root=output)
        loaded.append({"model": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": before,
                       "metrics": calculate_metrics(original.trace), "historical_event_match": exact_replay})
    imported_origins = [str(Path(m.__file__).resolve()) for m in list(sys.modules.values()) if getattr(m, "__file__", None)]
    assert not any("railway_project" in name for name in imported_origins)
    result = {"status": "passed", "demo_makespan_seconds": 47,
              "cpsat_status": cp.metadata["status"], "cpsat_objective_seconds": cp.metadata["objective_seconds"],
              "cpsat_verified": True, "loaded_pretrained_models": loaded,
              "loaded_count": len(loaded), "exact_historical_best_policy_event_matches": matched,
              "original_platform_imports_blocked": True, "original_project_file_access_blocked": True,
              "original_models_retrained": False}
    atomic_record(output / "acceptance.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cfar(output, resume, pause):
    from wafer_sched.agent.cli import run_study
    study = json.loads((PROJECT_ROOT / "configs/wafer_sched/agent/stage6_study.json").read_text(encoding="utf-8"))
    study["limits"] = {"max_rounds": 5, "total_seconds": 120, "max_experiment_seconds": 40, "max_decisions": 4096}
    scenario = study["development"][1]
    result = run_study(study, scenario, "deterministic", output, seed=0, resume=resume, pause_after=pause)
    if not pause:
        assert result["rounds"] >= 5
        assert result["constraint_pass_rate"] == 1
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["numerical", "cfar"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pause-after", type=int)
    args = parser.parse_args()
    if args.operation == "numerical":
        numerical(resolve_path(args.output))
    else:
        cfar(args.output, args.resume, args.pause_after)


if __name__ == "__main__":
    main()
