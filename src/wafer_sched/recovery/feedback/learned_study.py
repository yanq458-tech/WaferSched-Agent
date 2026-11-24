"""Prospective frozen comparison of learned and hand-written repair-query selection."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import shutil
from time import perf_counter

from .. import holdout, terminal_exact
from ..continuation import Continuation
from ..evidence_study import save
from ..policy_retest import pin
from . import local_outcomes
from .local_outcomes import planner
from . import exclusive_check, learned_query, policy, study, value_query

SEED = 92864121
DEFAULT = Path("results/local/learned-query-001")


def read(path):
    return json.loads(path.read_bytes())


def signature(data):
    cfg = dict(data["config"])
    cfg.pop("name", None)
    return sha256(json.dumps({**data,"config":cfg},sort_keys=True,separators=(",",":")).encode()).hexdigest()


def source_hashes():
    files = list(Path(__file__).parent.glob("*.py")) + [Path(local_outcomes.__file__),Path(planner.__file__)]
    return {**study.sources(), **{p.relative_to(Path(__file__).parent).as_posix():holdout.digest(p) for p in files}}


PREVIOUS = Path("results/recovery/feedback-study/learned-query-001")
VALUE_SEED = 30674117


def freeze(root, compare_value=False, local_value=False):
    if (root/"freeze.json").exists() or (root/"runs").exists():
        raise FileExistsError(root)
    seen, seeds = set(), set()
    base_seed = VALUE_SEED if compare_value else SEED
    historical = [*learned_query.ARCHIVES, holdout.OUT, holdout.ROOT]
    if compare_value:
        historical.append(PREVIOUS)
    if local_value:
        base_seed = 51936233
        historical.append(Path("results/recovery/feedback-study/value-agent-001"))
    for baseline in historical:
        for f in (baseline/"inputs").glob("*.json"):
            seen.add(signature(read(f)))
        for row in read(baseline/"manifest.json"):
            if "seed" in row:
                seeds.add(row["seed"])
    manifest = []
    for n in (16,20,24):
        for pressure in ("medium","high"):
            for i in range(3):
                seed = base_seed+len(manifest)
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
    save(root/"protocol.json",dict(arms=["human","learned","value"] if compare_value else ["human","learned"], budgets=[1,30], repeats=2, cores=holdout.CORES,
        order="balanced first order then reversed within same case and core",seed=base_seed,
        primary="repeat zero; reverse repeat reported separately", allocation=0.85,
        clock="warm processes; snapshot file read, deserialization, model loading, prediction, graph, validation and return timed; late result earns no bounds",
        comparator="policy.solve(mode=agent) in both arms, optional learned_query selector only",
        tools="same pilot, capacity, grid and exact; no old witnesses; no API; single-thread CP-SAT",
        value_estimator="grouped local outcomes; first actionable result then expected gain" if local_value else "regularized logistic outcome probabilities",
        training="observed outcome of historically selected lower/upper query; no counterfactual labels",
        source=source_hashes()))
    names = ["training.json", "model.json", "protocol.json", "manifest.json"]
    if compare_value:
        names.append("value-model.json")
    save(root/"freeze.json",{f:holdout.digest(root/f) for f in names})


def conflict_check(p, cert):
    check = {"terminal_capacity_workload":terminal_exact.verify_workload,
             "terminal_pending_residence":terminal_exact.verify_pending,
             "exclusive_terminal_deadlines":exclusive_check.verify}[cert["kind"]]
    return check(p,cert)


def run_one(root, name, arm, budget):
    start = perf_counter()
    case = Continuation.from_dict(read(root/"inputs"/(name+".json")))
    choose = None
    if arm == "value":
        model = read(root/"value-model.json")
        choose = planner.selector(model) if "neighbors" in model else value_query.selector(model)
    elif arm == "learned":
        choose = learned_query.selector(read(root/"model.json"))
    elif arm != "human":
        raise ValueError(arm)
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
    arms = read(root/"protocol.json")["arms"]
    for idx,item in items:
        name=item["case"]
        assert holdout.digest(root/"inputs"/(name+".json"))==item["sha256"]
        for rep in range(2):
            shift = idx % len(arms)
            order = arms[shift:] + arms[:shift]
            if rep:
                order.reverse()
            for arm in order:
                record=run_one(root,name,arm,budget)
                save(root/"runs"/str(budget)/name/f"{rep}-{arm}.json",dict(record,rep=rep,core=core,order=order))


def benchmark(root):
    assert source_hashes()==read(root/"protocol.json")["source"]
    assert all(holdout.digest(root/k)==v for k,v in read(root/"freeze.json").items())
    if (root/"runs").exists():
        raise FileExistsError(root/"runs")
    items=read(root/"manifest.json")
    random.Random(read(root/"protocol.json")["seed"]).shuffle(items)
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
    parser.add_argument("--value-study",action="store_true",help="Compare both frozen selectors with the human policy on a new cohort")
    parser.add_argument("--local-value",action="store_true",help="Use grouped empirical outcomes, with a fresh disjoint cohort")
    args=parser.parse_args()
    if args.local_value:
        args.value_study = True
    if args.action=="all":
        args.root.mkdir(parents=True,exist_ok=False)
        if args.value_study:
            archive_freeze = read(PREVIOUS/"freeze.json")
            for name in ("training.json","model.json"):
                if holdout.digest(PREVIOUS/name) != archive_freeze[name]:
                    raise ValueError("Unexpected archived training corpus or model")
                shutil.copyfile(PREVIOUS/name,args.root/name)
            observations = read(args.root/"training.json")["observations"]
            model = local_outcomes.train(observations) if args.local_value else value_query.train(observations)
            save(args.root/"value-model.json", model)
        else:
            learned_query.train(args.root)
    if args.action in ("all","freeze"):
        freeze(args.root,args.value_study,args.local_value)
    if args.action in ("all","benchmark"):
        if os.environ.get("PYTHONHASHSEED")!="0":
            parser.error("Set PYTHONHASHSEED=0 before starting Python")
        benchmark(args.root)
