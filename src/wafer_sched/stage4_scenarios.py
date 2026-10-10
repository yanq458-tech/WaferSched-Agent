"""Static instance suite; no hidden disturbance or environment seed sampling."""

import json
from pathlib import Path

from .artifacts import PROJECT_ROOT
from .config import load_config, seconds


def load_suite(path: Path | None = None):
    root = PROJECT_ROOT / "configs/wafer_sched"
    path = path or root / "stage4_suite.json"
    suite = json.loads(path.read_text(encoding="utf-8"))
    names = set()
    for row in suite["scenarios"]:
        if row["scenario"] in names:
            raise ValueError("Duplicate study scenario")
        names.add(row["scenario"])
        config_path = (root / row["config"]).resolve()
        if not config_path.is_relative_to(root.resolve()):
            raise ValueError("Configuration escapes study directory")
        seconds(row["window_seconds"], "observation window")
        seconds(row["solver_seconds"], "solver budget")
        row["equipment"] = load_config(config_path)
    return suite
