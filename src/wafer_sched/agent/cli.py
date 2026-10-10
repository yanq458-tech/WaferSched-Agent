"""Research entry point with validated configuration, never railway write-back."""

import argparse
import json
from pathlib import Path

from .experiment_runner import ExperimentRunner, ResearchLimits
from ..infrastructure.paths import resolve_path
from .planner import CPBudgetPlanner, DeterministicPlanner, FixedOrderPlanner, SemanticaLLMPlanner


def run_study(study, scenario, planner_name, output_root, *, seed=0, resume=False, pause_after=None):
    planners = {"deterministic": DeterministicPlanner, "cp_adaptive": CPBudgetPlanner,
                "fixed": lambda: FixedOrderPlanner(study["fixed_order"]),
                "llm": lambda: SemanticaLLMPlanner(allow_llm_egress=study.get("allow_llm_egress", False))}
    if planner_name not in planners:
        raise ValueError("Unsupported planning mode")
    return ExperimentRunner().run(config_path=scenario["config"], scenario_id=scenario["name"],
        window_seconds=scenario["window_seconds"], planner=planners[planner_name](), output_root=output_root,
        candidates=study["candidates"], seed=seed, limits=ResearchLimits(**study["limits"]),
        resume=resume, pause_after=pause_after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", default="configs/wafer_sched/agent/stage6_study.json")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--planner", choices=["deterministic", "fixed", "llm", "cp_adaptive"], default="deterministic")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pause-after", type=int)
    args = parser.parse_args()
    study = json.loads(resolve_path(args.study).read_text(encoding="utf-8"))
    scenario = next(row for row in study["development"] if row["name"] == args.scenario)
    summary = run_study(study, scenario, args.planner, args.output, seed=args.seed,
                        resume=args.resume, pause_after=args.pause_after)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
