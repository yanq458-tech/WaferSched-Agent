"""Repeat known short-budget regressions separately from final out-of-sample evaluation."""

import argparse
import json
from pathlib import Path

from .diagnosis import ROOT
from .study import runner
from ..continuation import Continuation, delta
from ..dispatch import replay_incident
from ..replay import replay_recovery
from .exclusive_check import verify
from ..evidence_study import save
from ..policy_retest import pin
from ..terminal_diagnostics import profile


def recheck(output):
    output.mkdir(parents=True, exist_ok=False)
    cases = ("new-16-m-f1", "new-16-m-f2", "new-16-m-f3", "new-20-h-f3")
    pin(6)
    for repeat in (0, 1):
        for name in cases[::1 if repeat == 0 else -1]:
            raw = json.loads((ROOT / "holdout" / "inputs" / (name + ".json")).read_bytes())
            record = profile(Continuation.from_dict(raw), "agent", 1, runner=runner)
            save(output / f"{name}-{repeat}.json", record)
            print(name, repeat, record["metrics"]["status"], record["metrics"]["wall_seconds"], flush=True)


def verify_development(output):
    rows = []
    for path in sorted(output.glob("new-*.json")):
        name, repeat = path.stem.rsplit("-", 1)
        case = Continuation.from_dict(json.loads((ROOT / "holdout" / "inputs" / (name + ".json")).read_bytes()))
        p, prefix = case.prepare()
        run = json.loads(path.read_bytes())
        m, e = run["metrics"], run["evidence"]
        if e["schedule"]:
            r = e["witness_repair"]
            v = replay_recovery(p, max(0, delta(r, prefix["offset"])), e["schedule"])
            assert v["valid"], v["errors"]
            replay_incident(case, prefix, dict(witness_repair_delay_seconds=r, makespan_seconds=e["raw_makespan"]),
                            {"verification": v})
            check = "original_simulator_double_replay"
        elif m["raw_status"] == "INFEASIBLE_AT_ZERO":
            assert verify(p, e["certificate"])
            check = "independent_exclusive_arithmetic"
        else:
            check = "no_witness_or_zero_proof"
        rows.append(dict(case=name, repeat=int(repeat), status=m["status"], raw=m["raw_status"],
                         wall_seconds=m["wall_seconds"], check=check))
    if not rows:
        raise ValueError("No development runs found")
    save(output / "audit.json", rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    (verify_development if args.verify else recheck)(args.out)
