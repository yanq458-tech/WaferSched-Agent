"""Run explicit stage-five gates; use a fresh output directory for reproduction."""

import argparse
import json
from pathlib import Path
import sys

# Direct script execution and module execution use the same existing src namespace.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def run(root, phase):
    from wafer_sched.infrastructure.io import atomic_record
    from wafer_sched.config import load_config
    from wafer_sched.rl.evaluation import RLEvaluationRunner
    from wafer_sched.rl.policy import TrainedPolicyAdapter
    from wafer_sched.rl.reporting import generate_plots
    from wafer_sched.rl.training import RLTrainingRunner, load_training_config, make_env, masked_episode

    root = Path(root)
    config_root = PROJECT_ROOT / "configs/wafer_sched/rl"
    if phase in {"all", "smoke"}:
        root.mkdir(parents=True, exist_ok=False)
        specification = load_training_config(config_root / "smoke_training.json")
        RLTrainingRunner().run(specification, root / "smoke")
        episodes = json.loads((root / "smoke/seed-0/episode_summaries.json").read_text(encoding="utf-8"))
        if not episodes or any(row["constraint_violations"] or row["mask_mismatches"] for row in episodes):
            raise RuntimeError("Short training safety gate failed")
        adapter = TrainedPolicyAdapter.load(root / "smoke/seed-0/models/best.zip")
        config = load_config(PROJECT_ROOT / specification["train_scenarios"][0]["config"])
        env = make_env(config, specification)
        summary = masked_episode(adapter.model, env)
        if summary["completion_rate"] != 1 or summary["mask_mismatches"]:
            raise RuntimeError("Short training loaded-model execution gate failed")
        atomic_record(root / "smoke_gate.json", {"passed": True, "real_training_episodes": len(episodes),
                                                 "loaded_model_execution": summary})
        env.close()
    if phase in {"all", "train"}:
        gate = json.loads((root / "smoke_gate.json").read_text(encoding="utf-8"))
        if not gate["passed"]:
            raise RuntimeError("Complete smoke gate before increasing training budget")
        for group in ("small", "medium"):
            RLTrainingRunner().run(load_training_config(config_root / f"{group}_training.json"), root / "training" / group)
    if phase in {"all", "evaluate"}:
        RLEvaluationRunner().run(config_root / "evaluation_suite.json", root / "training", root / "evaluation")
    if phase in {"all", "plots"}:
        generate_plots(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results/wafer_sched/stage5")
    parser.add_argument("--phase", choices=("all", "smoke", "train", "evaluate", "plots"), default="all")
    args = parser.parse_args()
    run(args.output, args.phase)


if __name__ == "__main__":
    main()
