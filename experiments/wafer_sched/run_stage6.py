"""python -m experiments.wafer_sched.run_stage6 --phase development|budgets|freeze|holdout|plots|all"""

import argparse
from pathlib import Path

from wafer_sched.agent.evaluation import StageSixEvaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["development", "budgets", "freeze", "holdout", "plots", "all"], default="all")
    parser.add_argument("--study", default="configs/wafer_sched/agent/stage6_study.json")
    parser.add_argument("--output", type=Path, default=Path("results/wafer_sched/stage6"))
    args = parser.parse_args()
    evaluation = StageSixEvaluation(args.study, args.output)
    phases = ["development", "budgets", "freeze", "holdout", "plots"] if args.phase == "all" else [args.phase]
    for phase in phases:
        if phase == "plots":
            from wafer_sched.agent.reporting import plot_stage6
            plot_stage6(evaluation.root)
            from experiments.wafer_sched.refine_stage6_plots import refine
            refine(evaluation.root)
            from experiments.wafer_sched.summarize_stage6 import summarize
            summarize(evaluation.root)
        else:
            getattr(evaluation, phase)()


if __name__ == "__main__":
    main()
