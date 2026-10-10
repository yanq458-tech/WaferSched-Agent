"""Declare unseen holdout equipment BEFORE running development feedback loops."""

import copy
import hashlib
import json

from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.config import EquipmentConfig


def prepare():
    root = PROJECT_ROOT / "configs/wafer_sched/agent"
    declarations = [
        ("F_competition.json", "U_recipe_mix", 5, 500,
         {"CLEAN": {"c_x": 4, "c_y": 15}, "ALT": {"c_x": 12, "c_y": 3},
          "RINSE": {"r_x": 10, "r_y": 6}}, {"pick_seconds": 1, "move_seconds": 2, "place_seconds": 1}),
        ("G_dual_bottleneck.json", "U_slow_transport", 6, 800,
         {"CLEAN": {"c_x": 11, "c_y": 19}, "RINSE": {"r_x": 21, "r_y": 7},
          "DRY": {"d_x": 6, "d_y": 12}}, {"pick_seconds": 3, "move_seconds": 4, "place_seconds": 2})]
    sealed = {}
    for source, name, count, window, recipes, robot in declarations:
        path = root / f"{name}.json"
        configuration = json.loads((PROJECT_ROOT / "configs/wafer_sched" / source).read_text(encoding="utf-8"))
        configuration["name"], configuration["robot"] = name, robot
        for chamber in configuration["chambers"]:
            chamber["processing_times"] = recipes[chamber["id"]]
        original = copy.deepcopy(configuration["wafers"])
        configuration["wafers"] = [dict(copy.deepcopy(original[i % len(original)]), id=f"W{i+1:02d}") for i in range(count)]
        EquipmentConfig.from_dict(configuration)
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != configuration:
                raise ValueError("Sealed holdout may not be altered")
        else:
            atomic_record(path, configuration)
        sealed[name] = {"path": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "window_seconds": window, "pre_evaluation_declaration": True}
    target = root / "holdout_seal.json"
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != sealed:
            raise ValueError("Holdout seal differs")
    else:
        atomic_record(target, sealed)
    return sealed


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
