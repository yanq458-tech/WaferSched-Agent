"""Frozen second holdout. The policies receive only the incident and their time allocation."""

import argparse
import json
import platform
import random
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

import ortools
from .. import holdout
from ..continuation import Continuation
from ..evidence_study import save
from ..policy_retest import pin
from ..terminal_diagnostics import profile
from .diagnosis import ROOT
from .policy import solve

METHODS = ("legacy", "fixed", "plain", "agent")
SEED = 3940721


def sources():
    return {
        **holdout.code_hashes(),
        **{
            "feedback/" + name: holdout.digest(Path(__file__).with_name(name))
            for name in ("policy.py", "grid.py", "capacity.py", "exact.py", "study.py", "exclusive_check.py", "replay_state.py")
        },
    }


def generate(root, final=False):
    methods = ("fixed", "plain", "agent") if final else METHODS
    seed_base = 6815033 if final else SEED
    root.mkdir(parents=True, exist_ok=False)
    save(
        root / "protocol.json",
        dict(
            methods=methods,
            seed=seed_base,
            cores=holdout.CORES,
            scale=[16, 20, 24],
            regime="frontier",
            independent_seeds_per_cell=3,
            pressure=["medium", "high"],
            budgets=[1, 30],
            workers=1,
            allocation=0.85,
            repeats="1s twice; 30s reverse all arms when at least two proof classifications differ",
            legacy="frozen previous fixed portfolio",
            fixed="new tools: pilot, capacity, upper, zero if no witness, midpoint",
            plain="feedback policy without graph",
            agent="same policy with LangGraph",
            short_feedback="probe route cap before building pilot CP model" if final else None,
            toolkit="includes exclusive single-chamber conflict and bounded replay log" if final else None,
            versions=dict(python=platform.python_version(), ortools=ortools.__version__),
            source=sources(),
        ),
    )
    old_hash = {
        v["sha256"]
        for path in ([holdout.ROOT, holdout.OUT, ROOT / "holdout"] if final else [holdout.ROOT, holdout.OUT])
        for v in json.loads((path / "manifest.json").read_bytes())
    }
    historical_seeds = set()
    if final:
        for old in (holdout.OUT, ROOT / "holdout"):
            historical_seeds.update(row["seed"] for row in json.loads((old / "manifest.json").read_bytes()))
    manifest = []
    for n in (16, 20, 24):
        for pressure in ("medium", "high"):
            for rep in range(3):
                seed = seed_base + len(manifest)
                assert seed not in historical_seeds
                raw, stats = holdout.snapshot(n, pressure, "frontier", seed)
                prefix = "blind" if final else "new"
                name = f"{prefix}-{n}-{pressure[0]}-f{rep + 1}"
                path = root / "inputs" / (name + ".json")
                save(path, raw)
                h = holdout.digest(path)
                assert h not in old_hash
                old_hash.add(h)
                manifest.append(
                    dict(
                        case=name,
                        wip=n,
                        pressure=pressure,
                        regime="frontier",
                        seed=seed,
                        sha256=h,
                        **stats,
                    )
                )
    save(root / "manifest.json", manifest)
    save(
        root / "freeze.json",
        {s: holdout.digest(root / (s + ".json")) for s in ("manifest", "protocol")},
    )


def runner(case, method, budget):
    if method == "legacy":
        return holdout.run_method(case, "fixed", budget)
    return solve(case, budget, method)


def lane(root, budget, items, core):
    pin(core)
    methods = json.loads((root / "protocol.json").read_bytes())["methods"]
    for i, item in items:
        name = item["case"]
        path = root / "inputs" / (name + ".json")
        assert holdout.digest(path) == item["sha256"]
        raw = json.loads(path.read_bytes())
        k = i % len(methods)
        order = methods[k:] + methods[:k]
        if (i // len(methods)) % 2:
            order.reverse()
        for rep in (0, 1):
            statuses = []
            for method in order:
                record = profile(Continuation.from_dict(raw), method, budget, runner=runner)
                record.pop("trace")
                record.update(case=name, core=core, repeat=rep, order=order.copy())
                statuses.append(record["metrics"]["status"])
                save(root / f"b{budget}" / name / f"{rep}-{method}.json", record)
            if budget == 30 and len(set(statuses)) == 1:
                break
            order.reverse()


def benchmark(root, budget):
    freeze = json.loads((root / "freeze.json").read_bytes())
    assert all(holdout.digest(root / (s + ".json")) == v for s, v in freeze.items())
    assert sources() == json.loads((root / "protocol.json").read_bytes())["source"]
    (root / f"b{budget}").mkdir(exist_ok=False)
    items = json.loads((root / "manifest.json").read_bytes())
    random.Random(json.loads((root / "protocol.json").read_bytes())["seed"]).shuffle(items)
    tasks = list(enumerate(items))
    with ProcessPoolExecutor(max_workers=len(holdout.CORES)) as pool:
        fs = [
            pool.submit(lane, root, budget, tasks[i :: len(holdout.CORES)], core)
            for i, core in enumerate(holdout.CORES)
        ]
        for f in fs:
            f.result()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["generate", "benchmark", "solve"])
    ap.add_argument("--final", action="store_true", help="Freeze the fresh three-arm closeout corpus")
    ap.add_argument("--root", type=Path, default=ROOT / "holdout")
    ap.add_argument("--budget", type=int, choices=[1, 30], default=30)
    ap.add_argument("--incident", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.action == "generate":
        generate(args.root, args.final)
    elif args.action == "benchmark":
        benchmark(args.root, args.budget)
    else:
        if not args.incident or not args.out:
            ap.error("solve requires --incident and --out")
        result = profile(
            Continuation.from_dict(json.loads(args.incident.read_bytes())),
            "agent",
            args.budget,
            runner=runner,
        )
        save(args.out, result)
