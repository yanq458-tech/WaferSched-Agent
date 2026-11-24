"""Prospective frozen comparison of learned and hand-written repair-query selection."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import random
from time import perf_counter

from .. import holdout, terminal_exact
from ..continuation import Continuation
from ..evidence_study import save
from ..policy_retest import pin
from . import exclusive_check, learned_query, policy, study

SEED = 92864121
DEFAULT = Path("results/local/learned-query-001")


def read(path):
    return json.loads(path.read_bytes())


def signature(data):
    cfg = dict(data["config"])
    cfg.pop("name", None)
    return sha256(json.dumps({**data,"config":cfg},sort_keys=True,separators=(",",":")).encode()).hexdigest()


def source_hashes():
    files = list(Path(__file__).parent.glob("*.py"))
    return {**study.sources(), **{p.name:holdout.digest(p) for p in files}}


def freeze(root):
    if (root/"freeze.json").exists() or (root/"runs").exists():
        raise FileExistsError(root)
    seen, seeds = set(), set()
    for baseline in (*learned_query.ARCHIVES, holdout.OUT, holdout.ROOT):
        for f in (baseline/"inputs").glob("*.json"):
            seen.add(signature(read(f)))
        for row in read(baseline/"manifest.json"):
            if "seed" in row:
                seeds.add(row["seed"])
    manifest = []
    for n in (16,20,24):
        for pressure in ("medium","high"):
            for i in range(3):
                seed = SEED+len(manifest)
                raw, info = holdout.snapshot(n,pressure,"frontier",seed)
                sig = signature(raw)
                if sig in seen or seed in seeds:
                    raise ValueError("Duplicate snapshot or seed")
                seen.add(sig)
                name = f"{n}-{pressure[0]}-{i+1}"
                path = root/"inputs"/(name+".json")
                save(path,raw)
                manifest.append(dict(case=name,seed=seed,sha256=holdout.digest(path),signature=sig,**info))
    save(root/"manifest.json",manifest)
    save(root/"protocol.json",dict(arms=["human","learned"], budgets=[1,30], repeats=2, cores=holdout.CORES,
        order="balanced first order then reversed within same case and core",seed=SEED,
        primary="repeat zero; reverse repeat reported separately", allocation=0.85,
        clock="warm processes; snapshot file read, deserialization, model loading, prediction, graph, validation and return timed; late result earns no bounds",
        comparator="policy.solve(mode=agent) in both arms, optional learned_query selector only",
        tools="same pilot, capacity, grid and exact; no old witnesses; no API; single-thread CP-SAT",
        training="observed outcome of historically selected lower/upper query; no counterfactual labels",
        source=source_hashes()))
    save(root/"freeze.json",{f:holdout.digest(root/f) for f in ("training.json","model.json","protocol.json","manifest.json")})


def conflict_check(p, cert):
    check = {"terminal_capacity_workload":terminal_exact.verify_workload,
             "terminal_pending_residence":terminal_exact.verify_pending,
             "exclusive_terminal_deadlines":exclusive_check.verify}[cert["kind"]]
    return check(p,cert)


def run_one(root, name, arm, budget):
    start = perf_counter()
    case = Continuation.from_dict(read(root/"inputs"/(name+".json")))
    choose = learned_query.selector(read(root/"model.json")) if arm=="learned" else None
    allocation = max(0, budget*0.85 - (perf_counter()-start))
    raw = policy.solve(case,allocation,"agent",query_selector=choose,conflict_checker=conflict_check)
    lo,hi = raw.get("verified_feasible_lower_seconds"),raw.get("finite_upper_seconds")
    schedule = (raw.get("best") or {}).get("schedule")
    if lo is not None and (not schedule or not raw.get("verification_valid")):
        raise ValueError("Bound lacks verified witness")
    status=raw["status"]
    if status=="FINITE" and (lo is None or lo!=hi):
        raise ValueError(("Missing matching bounds",lo,hi))
    if status=="INFEASIBLE_AT_ZERO" and schedule:
        raise ValueError("Contradictory proof and witness")
    elapsed=perf_counter()-start
    late=elapsed>budget
    return dict(case=name,arm=arm,budget=budget,wall=elapsed,late=late,status="UNKNOWN" if late else status,
                lower=None if late else lo,upper=None if late else hi,raw=raw)


def lane(root, items, core, budget):
    pin(core)
    for idx,item in items:
        name=item["case"]
        assert holdout.digest(root/"inputs"/(name+".json"))==item["sha256"]
        for rep in range(2):
            order=["human","learned"] if (idx+rep)%2==0 else ["learned","human"]
            for arm in order:
                record=run_one(root,name,arm,budget)
                save(root/"runs"/str(budget)/name/f"{rep}-{arm}.json",dict(record,rep=rep,core=core,order=order))


def benchmark(root):
    assert source_hashes()==read(root/"protocol.json")["source"]
    assert all(holdout.digest(root/k)==v for k,v in read(root/"freeze.json").items())
    if (root/"runs").exists():
        raise FileExistsError(root/"runs")
    items=read(root/"manifest.json")
    random.Random(SEED).shuffle(items)
    jobs=list(enumerate(items))
    for budget in (1,30):
        with ProcessPoolExecutor(len(holdout.CORES)) as pool:
            fs=[pool.submit(lane,root,jobs[i::len(holdout.CORES)],core,budget) for i,core in enumerate(holdout.CORES)]
            for f in fs:
                f.result()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("all","freeze","benchmark"))
    parser.add_argument("--root",type=Path,default=DEFAULT)
    args=parser.parse_args()
    if args.action=="all":
        args.root.mkdir(parents=True,exist_ok=False)
        learned_query.train(args.root)
    if args.action in ("all","freeze"):
        freeze(args.root)
    if args.action in ("all","benchmark"):
        if os.environ.get("PYTHONHASHSEED")!="0":
            parser.error("Set PYTHONHASHSEED=0 before starting Python")
        benchmark(args.root)
