"""Fixed worker module for a killable experiment; stdin contains only validated data."""

import json
from pathlib import Path
import sys

from wafer_sched.infrastructure.io import atomic_record
from .skills import execute_experiment


def main():
    request = json.loads(sys.stdin.buffer.read(1048576))
    try:
        result = execute_experiment(request)
        atomic_record(Path(request["context"]["experiment_directory"]) / "worker_result.json", result)
    except Exception as exc:
        # Exception text can contain external secrets/paths: retain type only.
        atomic_record(Path(request["context"]["experiment_directory"]) / "worker_failure.json",
                      {"error_type": type(exc).__name__})
        raise


if __name__ == "__main__":
    main()
