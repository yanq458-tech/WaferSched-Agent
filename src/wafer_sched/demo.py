"""Run the hand-checkable equipment case using the verification-only driver."""

import argparse
import json
from pathlib import Path

from .artifacts import PROJECT_ROOT, event_text, save_run
from .config import load_config
from .driver import run_validation_driver
from .metrics import calculate_metrics
from .simulator import Simulator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument("--print-events", action="store_true")
    arguments = parser.parse_args()
    simulator = Simulator(load_config(arguments.config), seed=arguments.seed)
    outcome = run_validation_driver(simulator)
    directory = save_run(simulator, outcome, run_id=arguments.run_id)
    if arguments.print_events:
        for row in simulator.trace:
            print(event_text(row))
    print(json.dumps({"status": outcome["status"], "artifacts": str(directory),
                      "metrics": calculate_metrics(simulator.trace)}, ensure_ascii=False, indent=2))
    return 0 if outcome["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
