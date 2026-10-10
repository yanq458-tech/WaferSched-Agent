"""Bounded CPU MaskablePPO training, real episodes and validation-only selection."""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
from time import perf_counter

import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import configure
from stable_baselines3.common.monitor import Monitor

from wafer_sched.infrastructure.io import atomic_record
from ..artifacts import PROJECT_ROOT
from ..config import load_config
from .encoding import EncodingSchema
from .environment import WaferSchedulingEnv
from .reward import RewardWeights


def hardware_metadata():
    return {"python": platform.python_version(), "platform": platform.platform(),
            "processor": platform.processor(), "cpu_count": os.cpu_count(),
            "torch_threads": torch.get_num_threads(), "device": "cpu",
            "cuda_available": torch.cuda.is_available(),
            "versions": {key: importlib.metadata.version(key) for key in
                         ("torch", "gymnasium", "stable-baselines3", "sb3-contrib", "numpy")}}


def load_training_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {"name", "schema", "reward_weights", "train_scenarios", "validation_scenarios",
               "seeds", "total_timesteps", "learning_rate", "n_steps", "batch_size", "n_epochs",
               "gamma", "gae_lambda", "ent_coef", "network", "validation_frequency",
               "max_training_seconds", "max_simulation_seconds", "max_decisions", "model_subdirectory"}
    if set(data) != allowed:
        raise ValueError(f"Training configuration fields mismatch: {set(data) ^ allowed}")
    if len(set(data["seeds"])) != len(data["seeds"]) or not data["seeds"]:
        raise ValueError("Training seeds must be nonempty and unique")
    for key in ("total_timesteps", "n_steps", "batch_size", "n_epochs", "validation_frequency", "max_decisions"):
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError(f"Invalid positive integer {key}")
    if data["total_timesteps"] % data["n_steps"] or data["n_steps"] % data["batch_size"]:
        raise ValueError("Use complete rollouts and divisible batches; no hidden timestep rounding")
    if not 0 < data["gamma"] <= 1 or not 0 < data["gae_lambda"] <= 1:
        raise ValueError("Invalid discount or GAE lambda")
    if data["max_training_seconds"] <= 0 or data["validation_frequency"] < data["n_steps"]:
        raise ValueError("Invalid training budget/validation frequency")
    if Path(data["model_subdirectory"]).parts != ("models",):
        raise ValueError("Models must be stored in the owned run's models subdirectory")
    schema = EncodingSchema(**data["schema"])
    RewardWeights(**data["reward_weights"])
    for split in ("train_scenarios", "validation_scenarios"):
        if not data[split]:
            raise ValueError("Train and validation sets must be nonempty")
        for row in data[split]:
            path = (PROJECT_ROOT / row["config"]).resolve()
            if not path.is_relative_to(PROJECT_ROOT):
                raise ValueError("Scenario path escapes project")
            WaferSchedulingEnv(load_config(path), schema=schema)
    # Physical configurations, not names, must differ between training and validation.
    def signatures(rows):
        result = set()
        for row in rows:
            value = load_config(PROJECT_ROOT / row["config"]).to_dict()
            value.pop("name", None)
            result.add(json.dumps(value, sort_keys=True))
        return result
    if signatures(data["train_scenarios"]) & signatures(data["validation_scenarios"]):
        raise ValueError("Validation configuration overlaps training equipment/tasks")
    return data


def make_env(configs, specification, *, max_time=None):
    return WaferSchedulingEnv(configs, schema=EncodingSchema(**specification["schema"]),
                              reward_weights=RewardWeights(**specification["reward_weights"]),
                              max_simulation_seconds=specification["max_simulation_seconds"] if max_time is None else max_time,
                              max_decisions=specification["max_decisions"])


def masked_episode(model, env, *, seed=0):
    vector, _ = env.reset(seed=seed)
    elapsed = 0.0
    for _ in range(env.max_decisions):
        mask = env.action_masks()
        started = perf_counter()
        index, _ = model.predict(vector, deterministic=True, action_masks=mask)
        elapsed += perf_counter() - started
        vector, _, terminated, truncated, info = env.step(int(index))
        if terminated or truncated:
            return {**info["episode_summary"], "inference_seconds": elapsed}
    raise RuntimeError("Environment failed to enforce its decision budget")


class ResearchCallback(BaseCallback):
    def __init__(self, directory, specification, started):
        super().__init__()
        self.directory, self.specification, self.started = directory, specification, started
        self.episodes, self.validation_rows = [], []
        self.best_key, self.best_timestep = None, None
        self.wall_budget_reached = False
        self.csv_file = (directory / "episodes.csv").open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.csv_file, fieldnames=["episode", "timesteps", "scenario", "return",
                                                              "makespan_seconds", "completion_rate", "reason",
                                                              "decisions", "elapsed_simulation_seconds",
                                                              "mask_checks", "mask_mismatches", "constraint_violations"])
        self.writer.writeheader()
        self.step_file = (directory / "transition_rewards.csv").open("w", encoding="utf-8", newline="")
        self.step_writer = csv.DictWriter(self.step_file, fieldnames=["timesteps", "scenario", "action_index",
                                                                   "delta_seconds", "mask_valid", "mask_legal_count",
                                                                   "reward_components"])
        self.step_writer.writeheader()

    def validate(self):
        rows = []
        for row in self.specification["validation_scenarios"]:
            env = make_env(load_config(PROJECT_ROOT / row["config"]), self.specification)
            summary = masked_episode(self.model, env)
            rows.append({"scenario": row["name"], "summary": summary})
            env.close()
        mean_completion = sum(r["summary"]["completion_rate"] for r in rows) / len(rows)
        mean_makespan = sum(r["summary"]["metrics"]["makespan_seconds"]
                            if r["summary"]["metrics"]["makespan_seconds"] is not None
                            else self.specification["max_simulation_seconds"] for r in rows) / len(rows)
        key = (mean_completion, -mean_makespan)
        improved = self.best_key is None or key > self.best_key
        if improved:
            self.best_key, self.best_timestep = key, self.num_timesteps
            self.model.save(self.directory / "models/best.zip")
        self.validation_rows.append({"timesteps": self.num_timesteps, "mean_completion_rate": mean_completion,
                                     "mean_makespan_seconds": mean_makespan, "selected": improved, "scenarios": rows})
        atomic_record(self.directory / "validation.json", self.validation_rows)
        print(f"  validation t={self.num_timesteps}: completion={mean_completion:.3f} "
              f"makespan={mean_makespan:g}s selected={improved}", flush=True)

    def _on_step(self):
        for index, info in enumerate(self.locals["infos"]):
            self.step_writer.writerow({"timesteps": self.num_timesteps, "scenario": info["scenario"],
                                       "action_index": int(self.locals["actions"][index]),
                                       "delta_seconds": info["delta_seconds"], "mask_valid": info["mask_valid"],
                                       "mask_legal_count": info["mask_legal_count"],
                                       "reward_components": json.dumps(info["reward_components"], sort_keys=True)})
            summary = info.get("episode_summary")
            if summary is None:
                continue
            self.episodes.append(summary)
            self.writer.writerow({"episode": len(self.episodes), "timesteps": self.num_timesteps,
                                  "scenario": summary["scenario"], "return": summary["return"],
                                  "makespan_seconds": summary["metrics"]["makespan_seconds"],
                                  "completion_rate": summary["completion_rate"], "reason": summary["reason"],
                                  "decisions": summary["decisions"],
                                  "elapsed_simulation_seconds": summary["metrics"]["window_duration_seconds"],
                                  "mask_checks": summary["mask_checks"], "mask_mismatches": summary["mask_mismatches"],
                                  "constraint_violations": summary["constraint_violations"]})
            self.csv_file.flush()
        if self.num_timesteps % self.specification["validation_frequency"] == 0:
            self.step_file.flush()
            self.validate()
        if perf_counter() - self.started >= self.specification["max_training_seconds"]:
            self.wall_budget_reached = True
            return False
        return True

    def _on_training_end(self):
        self.validate()  # Includes the final gradient update; selection still validation-only.
        self.csv_file.close()
        self.step_file.close()
        atomic_record(self.directory / "episode_summaries.json", self.episodes)


class RLTrainingRunner:
    def run(self, specification, output_root):
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=False)
        atomic_record(output_root / "training_config.json", specification)
        source_hashes = {path.relative_to(PROJECT_ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted((PROJECT_ROOT / "src/wafer_sched").rglob("*.py"))}
        atomic_record(output_root / "source_sha256.json", source_hashes)
        atomic_record(output_root / "evaluation_suite_before_training.json", json.loads(
            (PROJECT_ROOT / "configs/wafer_sched/rl/evaluation_suite.json").read_text(encoding="utf-8")))
        manifest = {"status": "running", "group": specification["name"], "training_seeds": specification["seeds"],
                    "seed_semantics": "independent_algorithm_initialization_and_action_sampling_not_environment_disturbances",
                    "checkpoint_selection": "validation_completion_then_mean_makespan_only", "runs": []}
        atomic_record(output_root / "manifest.json", manifest)
        configs = [load_config(PROJECT_ROOT / row["config"]) for row in specification["train_scenarios"]]
        for seed in specification["seeds"]:
            torch.set_num_threads(1)
            torch.use_deterministic_algorithms(True)
            directory = output_root / f"seed-{seed}"
            (directory / "models").mkdir(parents=True, exist_ok=False)
            env = Monitor(make_env(configs, specification), filename=str(directory / "monitor.csv"))
            started = perf_counter()
            model = MaskablePPO("MlpPolicy", env, device="cpu", seed=seed, verbose=0,
                                learning_rate=specification["learning_rate"], n_steps=specification["n_steps"],
                                batch_size=specification["batch_size"], n_epochs=specification["n_epochs"],
                                gamma=specification["gamma"], gae_lambda=specification["gae_lambda"],
                                ent_coef=specification["ent_coef"],
                                policy_kwargs={"net_arch": {"pi": specification["network"], "vf": specification["network"]}})
            model.set_logger(configure(str(directory / "updates"), ["csv"]))
            callback = ResearchCallback(directory, specification, started)
            print(f"Training {specification['name']} seed={seed}, requested={specification['total_timesteps']}", flush=True)
            model.learn(total_timesteps=specification["total_timesteps"], callback=callback)
            model.save(directory / "models/final.zip")
            seconds = perf_counter() - started
            metadata = {"schema": specification["schema"], "reward_weights": specification["reward_weights"],
                        "training_group": specification["name"], "seed": seed,
                        "requested_timesteps": specification["total_timesteps"], "actual_timesteps": model.num_timesteps,
                        "best_checkpoint_timestep": callback.best_timestep,
                        "best_validation_key": list(callback.best_key),
                        "training_seconds": seconds, "wall_budget_reached": callback.wall_budget_reached,
                        "completed_episodes": len(callback.episodes), "hardware": hardware_metadata(),
                        "train_equipment": [config.to_dict() for config in configs],
                        "validation_equipment": [load_config(PROJECT_ROOT / row["config"]).to_dict()
                                                 for row in specification["validation_scenarios"]],
                        "fixed_decision_discount": specification["gamma"], "custom_smdp_discount": False,
                        "model_selection_uses_test_set": False}
            atomic_record(directory / "models/metadata.json", metadata)
            manifest["runs"].append({"seed": seed, **{key: metadata[key] for key in
                                                       ("actual_timesteps", "training_seconds", "completed_episodes",
                                                        "best_checkpoint_timestep", "wall_budget_reached")}})
            atomic_record(output_root / "manifest.json", manifest)
            env.close()
        manifest["status"] = "completed"
        atomic_record(output_root / "manifest.json", manifest)
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    RLTrainingRunner().run(load_training_config(args.config), args.output)


if __name__ == "__main__":
    main()
