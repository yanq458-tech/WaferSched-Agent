"""Retest the six outstanding batch-B snapshots with the frozen timing implementation."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import platform
import random

import ortools
from wafer_sched.recovery import holdout
from wafer_sched.recovery.evidence_study import save
from wafer_sched.recovery.feedback.learned_study import read, run_one, source_hashes
from wafer_sched.recovery.policy_retest import pin

ARCHIVE = Path("results/recovery/feedback-study/value-agent-002")
CASES = ("16-h-1", "16-h-2", "20-h-3", "24-h-1", "24-h-2", "24-h-3")
TIMING_COMMIT = "0cd54f4cbf4879b065c6b2fd36739840fd5b5076"


def worker(out, core, jobs, budget):
    pin(core)
    for case, first_order in jobs:
        for rep, order in enumerate((first_order, first_order[::-1])):
            for arm in order:
                record = run_one(ARCHIVE, case, arm, budget)
                save(out / "runs" / str(budget) / case / f"{rep}-{arm}.json",
                     dict(record, rep=rep, core=core, order=order))


def run(out):
    protocol = read(ARCHIVE / "protocol.json")
    if os.environ.get("PYTHONHASHSEED") != "0" or os.environ.get("OPENBLAS_NUM_THREADS") != "1":
        raise ValueError("Set PYTHONHASHSEED=0 and OPENBLAS_NUM_THREADS=1 before running.")
    if source_hashes() != protocol["source"]:
        raise ValueError(f"Set PYTHONPATH to src from the timing commit {TIMING_COMMIT}.")
    for name, digest in read(ARCHIVE / "freeze.json").items():
        if holdout.digest(ARCHIVE / name) != digest:
            raise ValueError(f"Frozen archive mismatch: {name}")
    manifest = read(ARCHIVE / "manifest.json")
    for row in manifest:
        if holdout.digest(ARCHIVE / "inputs" / (row["case"] + ".json")) != row["sha256"]:
            raise ValueError(row["case"])
    random.Random(protocol["seed"]).shuffle(manifest)
    cores = protocol["cores"]
    lanes = {core: [] for core in cores}
    orders = {}
    for index, row in enumerate(manifest):
        name = row["case"]
        if name in CASES:
            first = ["human", "value"] if len(orders) % 2 == 0 else ["value", "human"]
            core = cores[index % len(cores)]
            lanes[core].append((name, first))
            orders[name] = dict(core=core, first=first)
    if set(orders) != set(CASES):
        raise ValueError("Missing input")
    out.mkdir(parents=True, exist_ok=False)
    save(out / "protocol.json", dict(archive=ARCHIVE.as_posix(), source_commit=TIMING_COMMIT,
         frozen=read(ARCHIVE / "freeze.json"), cases=orders, budgets=protocol["budgets"],
         repeats=2, clock=protocol["clock"], seed=protocol["seed"], fraction=protocol["allocation"],
         python=platform.python_version(), ortools=ortools.__version__,
         input_hashes={r["case"]: r["sha256"] for r in manifest if r["case"] in CASES}))
    for seconds in protocol["budgets"]:
        with ProcessPoolExecutor(len(cores)) as pool:
            futures = [pool.submit(worker, out, core, jobs, seconds)
                       for core, jobs in lanes.items() if jobs]
            for future in futures:
                future.result()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    run(parser.parse_args().out)
