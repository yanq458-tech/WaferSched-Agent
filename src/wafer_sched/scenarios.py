"""Load declared study configurations; policies share identical equipment."""

import json

from .artifacts import PROJECT_ROOT
from .config import load_config, seconds


def study_scenarios():
    root = PROJECT_ROOT / "configs/wafer_sched"
    suite = json.loads((root / "stage3_suite.json").read_text(encoding="utf-8"))
    scenarios = []
    for row in suite["scenarios"]:
        path = (root / row["config"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Study configuration escapes its configuration directory")
        seconds(row["window_seconds"], "study window")
        scenarios.append((row["scenario"], load_config(path), row["window_seconds"]))
    return scenarios
