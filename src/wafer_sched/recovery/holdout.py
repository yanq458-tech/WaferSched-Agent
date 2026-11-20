"""Frozen out-of-sample terminal experiments. Run generate, benchmark, then audit."""

import argparse
import hashlib
import json
import platform
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

import ortools
from . import healthy_witness, terminal_exact, tail_ranks
from .conflict_evidence import best_bound, propagated_bounds, verify_bound
from .continuation import Continuation
from .evidence_study import ROOT, save
from .policy_retest import pin
from .short_budget import PreparedIncident
from .study_data import terminal_case
from .study_policy import adaptive
from .terminal_diagnostics import profile

OUT = Path("results/recovery/holdout-scale")
METHODS = ("single", "fixed", "plain", "agent")
SEED = 20261120
CORES = [2, 4, 6, 8]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(n, pressure, regime, seed):
    # Reuse the reachable admission history; only unused terminal routing and limits change.
    case = terminal_case(n, seed)
    raw = case.to_dict()
    rng = random.Random(seed)
    h = 2 if pressure == "high" else (n + 4) // 5
    healthy = [f"H{i}" for i in range(1, h + 1)]
    cfg = raw["config"]
    cfg["name"] = f"holdout-{n}-{pressure}-{regime}-{seed}"
    eligible = set(healthy + ["F"])
    cfg["chambers"] = [c for c in cfg["chambers"] if c["id"] in eligible or c["id"].startswith("S")]
    raw["snapshot"]["chambers"] = {
        k: v for k, v in raw["snapshot"]["chambers"].items() if k in eligible or k.startswith("S")
    }
    for i, w in enumerate(cfg["wafers"]):
        wid = w["id"]
        if i == 0 and regime != "bypass":
            route = ["F"]
        else:
            chosen = (
                healthy[0] if pressure == "high" and rng.random() < 0.7 else rng.choice(healthy)
            )
            route = [chosen]
            if pressure == "medium" and rng.random() < 0.65:
                route.append(rng.choice([c for c in healthy if c != chosen]))
            if rng.random() < 0.55:
                route.append("F")
        w["route"][-1]["chambers"] = route
        base = {"tight": 3 * n, "frontier": (35 * n) // 8, "bypass": 12 * n}[regime]
        raw["residency"][wid] = [base + rng.randrange(17) / 8, (12 + rng.randrange(25)) / 8]
        raw["holding"][wid] = [
            None,
            None if regime == "bypass" else 16 + rng.randrange(33) / 8,
            None,
        ]
    obj = Continuation.from_dict(raw)
    # Replay its history and compare all physical snapshot fields before enrolling the case.
    p, _ = PreparedIncident(**vars(obj)).prepare()
    assert len(p.config.wafers) == n and terminal_exact.terminal_domain(p)
    routes = [set(w["route"][-1]["chambers"]) for w in cfg["wafers"]]
    total = len(set.union(*routes))
    return raw, dict(
        eligible_terminals=total,
        wip_per_terminal=n / total,
        most_shared=max(sum(c in rr for rr in routes) for c in set.union(*routes)),
        single_choice=sum(len(rr) == 1 for rr in routes),
    )


def code_hashes():
    folder = Path(__file__).parent
    return {p.name: digest(p) for p in sorted(folder.glob("*.py")) if p.name != "holdout_review.py"}


def generate(root):
    root.mkdir(parents=True, exist_ok=False)
    spec = dict(
        seed=SEED,
        wip=[16, 20, 24],
        pressure=["medium", "high"],
        regime=["tight", "frontier", "bypass"],
        independent_seeds_per_cell=2,
        budgets_seconds=[1, 30],
        methods=METHODS,
        cores=CORES,
        workers_per_solve=1,
        allocation_fraction=0.85,
        replicates="1s all twice in reverse order; 30s reverse all four arms only on a proof-status disagreement",
        endpoints="wall <= budget and exact boundary category; warm imports, timed preparation/search/replay; offline synthetic terminal domain",
        fixed="same toolkit; precompute sound route cap, cheap conflict tests, always probe healthy construction up to 12%, then ranked and terminal exact",
        plain="unchanged adaptive(fast=True,graph=False); same decisions as graph without LangGraph",
        single="direct optimized terminal CP-SAT tool, with same route cap; includes native internal feedback",
        agent="unchanged adaptive(fast=True,graph=True)",
        versions=dict(python=platform.python_version(), ortools=ortools.__version__),
        source=code_hashes(),
    )
    save(root / "protocol.json", spec)
    old = {x["sha256"] for x in json.loads((ROOT / "manifest.json").read_bytes())}
    manifest = []
    for n in spec["wip"]:
        for pressure in spec["pressure"]:
            for regime in spec["regime"]:
                for rep in range(2):
                    seed = SEED + len(manifest)
                    name = f"{n}-{pressure[0]}-{regime[0]}{rep + 1}"
                    raw, info = snapshot(n, pressure, regime, seed)
                    path = root / "inputs" / (name + ".json")
                    save(path, raw)
                    h = digest(path)
                    assert h not in old and all(item["sha256"] != h for item in manifest)
                    manifest.append(
                        dict(
                            case=name,
                            wip=n,
                            pressure=pressure,
                            regime=regime,
                            seed=seed,
                            sha256=h,
                            **info,
                        )
                    )
    save(root / "manifest.json", manifest)
    save(
        root / "freeze.json",
        dict(manifest=digest(root / "manifest.json"), protocol=digest(root / "protocol.json")),
    )


def run_method(case, method, budget):
    if method in {"plain", "agent"}:
        return adaptive(case, budget, graph=method == "agent", fast=True)
    deadline = perf_counter() + budget
    case = PreparedIncident(**vars(case))
    p, prefix = case.prepare()
    domain = terminal_exact.terminal_domain(p)
    assert domain is not None
    cert = best_bound(p) or min(propagated_bounds(p), key=lambda c: c["upper_tick"], default=None)
    assert cert is None or verify_bound(p, cert)
    traces = []
    result = None
    if method == "fixed":
        conflict = terminal_exact.workload(domain) or terminal_exact.pending_conflict(p, domain)
        if conflict:
            return dict(
                status="INFEASIBLE_AT_ZERO",
                certificate=conflict,
                trace=[dict(tool=conflict["kind"], **conflict)],
            )
        result, note = healthy_witness.verified_bypass(
            case, p, prefix, min(deadline, perf_counter() + 0.12 * budget)
        )
        traces.append(dict(tool="healthy_completion", **note))
        if result is None:
            result = tail_ranks.ranked_recovery(case, p, prefix, domain, cert, deadline, fast=True)
    if result is None:
        result = terminal_exact.solve_terminal(case, p, prefix, domain, cert, deadline)
    assert result is not None
    result["trace"] = traces + result.get("trace", [])
    if cert:
        result.setdefault("certificate", cert)
    return result


def lane(root, items, budget, core):
    pin(core)
    for index, item in items:
        path = root / "inputs" / (item["case"] + ".json")
        assert digest(path) == item["sha256"]
        raw = json.loads(path.read_bytes())
        order = list(METHODS[index % 4 :] + METHODS[: index % 4])
        if (index // 4) % 2:
            order.reverse()
        for rep in (0, 1):
            statuses = []
            for method in order:
                value = profile(Continuation.from_dict(raw), method, budget, runner=run_method)
                value.pop("trace")
                value.update(case=item["case"], repeat=rep, core=core, order=order.copy())
                statuses.append(value["metrics"]["status"])
                save(root / f"b{budget}" / item["case"] / f"{rep}-{method}.json", value)
            if budget == 30 and len(set(statuses)) == 1:
                break
            order.reverse()


def benchmark(root, budget):
    frozen = json.loads((root / "freeze.json").read_bytes())
    assert (
        digest(root / "manifest.json") == frozen["manifest"]
        and digest(root / "protocol.json") == frozen["protocol"]
    )
    assert json.loads((root / "protocol.json").read_bytes())["source"] == code_hashes()
    (root / f"b{budget}").mkdir(exist_ok=False)
    items = json.loads((root / "manifest.json").read_bytes())
    random.Random(SEED).shuffle(items)
    ordered = list(enumerate(items))
    with ProcessPoolExecutor(max_workers=len(CORES)) as pool:
        futures = [
            pool.submit(lane, root, ordered[i :: len(CORES)], budget, c)
            for i, c in enumerate(CORES)
        ]
        for future in futures:
            future.result()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["generate", "benchmark"])
    ap.add_argument("--root", type=Path, default=OUT)
    ap.add_argument("--budget", type=int, choices=[1, 30], default=1)
    args = ap.parse_args()
    if args.action == "generate":
        generate(args.root)
    else:
        benchmark(args.root, args.budget)
