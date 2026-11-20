"""Paired deterministic-work replay of the two historical optimization entry points."""

import json
import hashlib
from unittest.mock import patch
from ortools.sat.python import cp_model
from ..holdout import OUT, run_method
from ..continuation import Continuation
from ..evidence_study import save
from ..policy_retest import pin
from pathlib import Path

ROOT = Path("results/recovery/feedback-study")


def main(work=0.5):
    pin(6)
    name = "20-m-f2"
    original = cp_model.CpSolver.solve
    records = []
    for method in ("single", "agent"):
        calls = []

        def controlled(s, model, *args, **kwargs):
            stub = s.parameters
            cpu_limit = stub.max_time_in_seconds
            stub.max_time_in_seconds = 120
            stub.max_deterministic_time = work
            raw = model.proto.SerializeToString()
            status = original(s, model, *args, **kwargs)
            calls.append(
                dict(
                    model_sha256=hashlib.sha256(raw).hexdigest(),
                    allotted_wall=cpu_limit,
                    controlled_parameters=str(stub),
                    status=s.status_name(status),
                    branches=s.num_branches,
                    conflicts=s.num_conflicts,
                    objective=s.objective_value,
                    best_bound=s.best_objective_bound,
                    deterministic=s.response_proto.deterministic_time,
                    wall=s.wall_time,
                )
            )
            return status

        with patch.object(cp_model.CpSolver, "solve", controlled):
            result = run_method(
                Continuation.from_dict(
                    json.loads((OUT / "inputs" / (name + ".json")).read_bytes())
                ),
                method,
                25.5,
            )
        records.append(dict(method=method, status=result["status"], calls=calls))
    a, b = [r["calls"][0] for r in records]
    for k in (
        "model_sha256",
        "controlled_parameters",
        "status",
        "branches",
        "conflicts",
        "objective",
        "best_bound",
    ):
        assert a[k] == b[k], (k, a, b)
    archive = []
    for i in (0, 1):
        for m in ("single", "agent"):
            d = json.loads((OUT / "b30" / name / f"{i}-{m}.json").read_bytes())
            archive.append(
                dict(
                    rep=i,
                    method=m,
                    metrics=d["metrics"],
                    phases=d["phases"],
                    calls=d["calls"],
                    trace=d["evidence"]["trace"],
                )
            )
    filename = "diagnosis-20-m-f2.json" if work == 0.5 else f"diagnosis-20-m-f2-work{work:g}.json"
    save(ROOT / filename, dict(archived=archive, controlled=records))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=float, default=0.5)
    main(parser.parse_args().work)
