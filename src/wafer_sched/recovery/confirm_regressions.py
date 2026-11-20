"""Post-hoc reverse-order check of slower completed proofs and weaker UNKNOWN bounds."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
from .continuation import delta
from .dispatch import replay_incident
from .evidence_study import ROOT, save
from .policy_retest import OLD, NEW, PROVED, quality, read_case, run_lane
from .replay import replay_recovery


def flags(a, b):
    if a["status"] == b["status"] == "UNKNOWN" and quality(a, b) == "worse":
        return "weaker_bounds"
    if a["status"] == b["status"] and a["status"] in PROVED and a["rho"] == b["rho"]:
        if a["status"] == "FINITE" and b["makespan"] > a["makespan"]:
            return "worse_makespan"
        if (
            b["wall_seconds"] - a["wall_seconds"] >= 0.05
            and b["wall_seconds"] >= 1.2 * a["wall_seconds"]
        ):
            return "slower_same_proof"
    return None


def run(folder):
    protocol = json.loads((folder / "protocol.json").read_bytes())
    target = folder / "secondary"
    if (target / "runs").exists():
        raise FileExistsError(target)
    groups = defaultdict(lambda: defaultdict(dict))
    for f in (folder / "runs").glob("*.json"):
        r = json.loads(f.read_bytes())["metrics"]
        groups[r["case"]][r["repeat"]][r["method"]] = r
    selected = {}
    lanes = defaultdict(list)
    lookup = {x["case"]: x for x in json.loads((ROOT / "manifest.json").read_bytes())}
    for name, reps in sorted(groups.items()):
        history = [(rep, flags(pair[OLD], pair[NEW])) for rep, pair in sorted(reps.items())]
        # Two complete primary pairs already test for persistent latency change.
        if len(reps) > 1 and all(
            flag not in ("weaker_bounds", "worse_makespan") for _, flag in history
        ):
            continue
        for rep, flag in reversed(history):
            if flag:
                a, b = reps[rep][OLD], reps[rep][NEW]
                lanes[a["core"]].append((lookup[name], int(a["first_in_pair"])))
                selected[name] = dict(screen=flag, repeat=rep, original=[a, b])
                break
    save(
        target / "selection.json",
        dict(
            criteria="Post hoc: same proof and >=50ms and >=20% slower, or weaker UNKNOWN interval or larger fixed-bound makespan",
            cases=selected,
        ),
    )
    if lanes:
        with ProcessPoolExecutor(max_workers=len(lanes)) as pool:
            futures = [
                pool.submit(run_lane, jobs, core, protocol["budget"], 1, target, False)
                for core, jobs in lanes.items()
            ]
            for f in futures:
                f.result()
    for name, item in selected.items():
        case = read_case(lookup[name])
        p, h = case.prepare()
        rows = []
        for method in (OLD, NEW):
            data = json.loads((target / "runs" / f"{name}-0-{method}.json").read_bytes())
            rows.append(data["metrics"])
            if data["schedule"]:
                r = data["witness_repair"]
                v = replay_recovery(p, max(0, delta(r, h["offset"])), data["schedule"])
                assert v["valid"]
                replay_incident(
                    case,
                    h,
                    dict(witness_repair_delay_seconds=r, makespan_seconds=data["raw_makespan"]),
                    {"verification": v},
                )
        proved = {(r["status"], r["rho"]) for r in rows + item["original"] if r["status"] in PROVED}
        assert len(proved) <= 1
        item["retest"] = rows
        item["retest_effect"] = flags(*rows)
        item["replicated"] = item["screen"] == item["retest_effect"]
    save(target / "results.json", selected)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    run(ap.parse_args().folder)
