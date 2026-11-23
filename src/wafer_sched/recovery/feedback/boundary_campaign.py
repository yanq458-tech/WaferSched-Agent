"""Checkpointed offline boundary search on the archived finite terminal problems."""
import argparse
import gzip
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from . import order_probe, slot_query
from .frontier_witness import lift
from .resume_endpoint import age_proof
from .route_resume import choices
from .target_queries import Continuation, digest, load, record_plan, terminal_domain

ARCHIVE = Path("results/local/offline-resume-008")
OUTPUT = Path("results/local/boundary-campaign-009")
ORDER = Path("results/local/fixed-queries-005/OrderSearch.exe")


def atomic(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")
    temp.replace(path)


def node(rank, upper, job=None, route=()):
    return dict(rank=rank, upper=upper, job=job, route=list(route), attempts=0)


def optimize(p, domain, part, lower, deadline, folder):
    k, upper = part["rank"], part["upper"]
    model, opts, idle, held = slot_query.build(p, domain, lower+1, k, last_job=part["job"])
    slot_query.add_gap_cuts(model, domain, k, opts, idle, held)
    repair = model.new_int_var(lower+1, upper, "repair_delay")
    _, pick, place, travel = domain
    period = pick+place+2*travel
    failed = defaultdict(list)
    for _, chamber, u, _, x in opts:
        if chamber == p.failed_chamber:
            failed[u].append(x)
    for u, lits in failed.items():
        used = model.new_bool_var("failed_chamber_load")
        model.add(sum(lits) == used)
        model.add(repair <= u*period+pick+travel+held[u]).only_enforce_if(used)
    model.maximize(repair)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 907 + part["attempts"]
    solver.parameters.max_time_in_seconds = max(0, deadline-perf_counter())
    status = solver.solve(model)
    if status == cp_model.MODEL_INVALID:
        raise ValueError(model.validate())
    info = dict(status=solver.status_name(status), branches=solver.num_branches,
                solver_seconds=solver.wall_time, search_from=lower+1, search_to=upper,
                seed=solver.parameters.random_seed)
    plan = None
    if status == cp_model.INFEASIBLE:
        upper = lower
    elif status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        q = solver.value(repair)
        bound = math.ceil(solver.best_objective_bound)
        if not lower < q <= bound:
            raise ValueError("Contradictory objective bound")
        upper = min(upper, bound)
        n = len(domain[0])
        seq, chambers = [None]*(2*n), [None]*n
        for j, c, u, v, x in opts:
            if solver.boolean_value(x):
                seq[u], seq[v], chambers[j] = 2*j, 2*j+1, c
        hit = lift(p, domain, seq, chambers, q, upper)
        if not hit:
            raise ValueError("Failed to retime the solver witness")
        info["attained"], plan = hit
    if upper < part["upper"]:
        raw = model.proto.SerializeToString(deterministic=True)
        (folder/"model.pb.gz").write_bytes(gzip.compress(raw, compresslevel=1))
        info["model_sha256"] = hashlib.sha256(raw).hexdigest()
        info["model_file"] = str(folder/"model.pb.gz")
    info["branch_upper"] = upper
    return info, plan


def split(part, domain):
    jobs = domain[0]
    if part["job"] is None:
        return [node(part["rank"], part["upper"], j) for j in range(len(jobs))]
    eligible = [i for i,j in enumerate(jobs) if len(j.choices)>1]
    if not eligible:
        return []
    j = max(eligible, key=lambda i: max(t for _,t in jobs[i].choices)-min(t for _,t in jobs[i].choices))
    return [node(part["rank"], part["upper"], part["job"], part["route"]+[[j,c]])
            for c,_ in jobs[j].choices]


def initialize(archive, out, order):
    jobs = {}
    inputs = {}
    binding = {"manifest": digest(archive/"manifest.json"), "ortools":ortools.__version__,
               "constructor":digest(order), "implementation":digest(Path(__file__))}
    for item in load(archive/"manifest.json"):
        name = item["case"]
        folder = archive/"certificates"/name
        ledger = folder/"ledger.json"
        if not ledger.exists():
            continue
        rec = load(ledger)
        if rec["status"] != "UNKNOWN":
            continue
        src = archive/"inputs"/(name+".json")
        if not digest(src)==rec["snapshot"]==item["sha256"]:
            raise ValueError(f"Snapshot mismatch: {name}")
        case = Continuation.from_dict(load(src))
        p,h = case.prepare()
        domain = terminal_domain(p)
        if domain is None or h["offset"]!=0 or rec["lower"] is None or rec["upper"] is None:
            raise ValueError(f"Expected finite terminal interval with a witness: {name}")
        lo,hi = rec["lower"]*p.scale,rec["upper"]*p.scale
        if lo!=int(lo) or hi!=int(hi) or lo>hi or hi>=2**50:
            raise ValueError(f"Invalid archived tick interval: {name}")
        plan = folder/"schedule.json"
        source = Path(rec["evidence"])
        binding[name] = [digest(src),digest(ledger),digest(plan),digest(source)]
        inputs[name] = (case,p,h,domain)
        jobs[name] = dict(scale=p.scale, lower=int(lo), initial=[int(lo),int(hi)],
                          witness=str(plan), source=str(source), turns=0,
                          parts=[node(k,int(hi)) for k in slot_query.ranks(domain)])
    if not jobs:
        raise ValueError("No archived UNKNOWN cases with finite intervals")
    checkpoint = out/"state.json"
    if checkpoint.exists():
        state = load(checkpoint)
        if state["binding"]!=binding:
            raise ValueError("Checkpoint inputs or implementation changed; use a new output directory")
    else:
        state = dict(binding=binding,jobs=jobs,history=[])
    for name,job in state["jobs"].items():
        case,p,h,_=inputs[name]
        q=job["lower"]
        actual=record_plan(case,p,h,q,load(Path(job["witness"])),out/"checked"/name)
        if round(actual*p.scale)!=q:
            raise ValueError(f"Replayed lower bound mismatch: {name}")
    return state,inputs


def upper(job):
    return max([job["lower"]]+[n["upper"] for n in job["parts"]])


def step(job, inputs, end, folder, order):
    case,p,h,domain=inputs
    lo,hi=job["lower"],upper(job)
    before=perf_counter()
    plan=None
    job["turns"]+=1
    if job["turns"]%4==1:
        # Alternate easier and more ambitious targets, keeping seed and feedback on disk.
        q=lo+1 if job["turns"]%8==1 else (lo+hi+1)//2
        seed=7907+job["turns"]
        hit=order_probe.search(p,domain,q,hi,order,max(0,end-perf_counter()),seed=seed)
        info=dict(tool="construct",target=q,seed=seed,status="UNKNOWN")
        if hit:
            info["attained"],plan=hit
            info["status"]="FEASIBLE"
    else:
        candidates=[n for n in job["parts"] if n["upper"]>lo]
        part=min(candidates,key=lambda n:(-n["upper"],n["attempts"],len(n["route"]),n["rank"]))
        route=choices(domain,part["route"])
        desc=dict(rank=part["rank"],job=part["job"],route=part["route"])
        tries=part["attempts"]
        if tries==1 and part["job"] is not None and len({c for j in route[0] for c,_ in j.choices})<=3:
            q=(lo+part["upper"]+1)//2
            period=route[1]+route[2]+2*route[3]
            grid=next(v for v in range(max(1,period//3),0,-1) if period%v==0)
            proof=age_proof(p,route,q,part["rank"],part["job"],grid,end)
            info=dict(tool="age_flow",target=q,status=proof["status"])
            if proof["status"]=="INFEASIBLE":
                atomic(folder/"dual.json",proof)
                info["certificate"]=str(folder/"dual.json")
                part["upper"]=q-1
        else:
            info,plan=optimize(p,route,part,lo,end,folder)
            info["tool"]="maximize_repair"
            part["upper"]=info["branch_upper"]
        part["attempts"]+=1
        info.update(desc)
        if info["status"]=="UNKNOWN" and part["attempts"]>=2:
            children=split(part,route)
            if children:
                job["parts"].remove(part)
                job["parts"].extend(children)
                info["split_into"]=len(children)
    if plan:
        actual=record_plan(case,p,h,info["attained"],plan,folder/"witness")
        tick=round(actual*p.scale)
        if not lo<tick<=hi:
            raise ValueError("New witness contradicts the archived interval")
        job.update(lower=tick,witness=str(folder/"witness"/"schedule.json"))
    job["parts"]=[n for n in job["parts"] if n["upper"]>job["lower"]]
    return dict(info,before=[lo,hi],after=[job["lower"],upper(job)],seconds=perf_counter()-before)


def run(archive,out,order,seconds,quantum):
    if not all(math.isfinite(t) and t>0 for t in (seconds,quantum)):
        raise ValueError("Positive finite budgets required")
    out.mkdir(parents=True,exist_ok=True)
    # OS releases the exclusive ownership automatically if the process exits.
    lock=sqlite3.connect(out/"writer.sqlite",timeout=0,isolation_level=None)
    try:
        lock.execute("BEGIN IMMEDIATE")
        state,inputs=initialize(archive,out,order)
        checkpoint=out/"state.json"
        atomic(checkpoint,state)
        start=perf_counter()
        end=start+seconds
        while perf_counter()<end:
            pending=[name for name,j in state["jobs"].items() if upper(j)>j["lower"]]
            if not pending: break
            # Rotate snapshots first. No large snapshot can starve the other five.
            name=min(pending,key=lambda n:state["jobs"][n]["turns"])
            job=state["jobs"][name]
            folder=out/"steps"/f"{len(state['history']):06}-{name}"
            # A crashed, uncommitted step is outside the ledger; keep its raw artifacts.
            if folder.exists():
                from uuid import uuid4
                folder=folder.with_name(folder.name+"-"+uuid4().hex)
            folder.mkdir(parents=True)
            info=step(job,inputs[name],min(end,perf_counter()+quantum),folder,order)
            state["history"].append(dict(case=name,**info))
            atomic(checkpoint,state)
        report={name:dict(initial=[x/j["scale"] for x in j["initial"]],
                          interval=[j["lower"]/j["scale"],upper(j)/j["scale"]],
                          status="FINITE" if upper(j)==j["lower"] else "UNKNOWN",
                          turns=j["turns"],witness=j["witness"]) for name,j in state["jobs"].items()}
        result=dict(cases=report,stop="all_proved" if all(v["status"]=="FINITE" for v in report.values()) else "budget",
                    elapsed_search_seconds=perf_counter()-start,requested_seconds=seconds)
        atomic(out/"summary.json",result)
        return result
    finally:
        lock.close()


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive",type=Path,default=ARCHIVE)
    ap.add_argument("--out",type=Path,default=OUTPUT)
    ap.add_argument("--constructor",type=Path,default=ORDER)
    ap.add_argument("--seconds",type=float,default=180)
    ap.add_argument("--slice",type=float,default=5)
    a=ap.parse_args()
    print(json.dumps(run(a.archive,a.out,a.constructor.resolve(strict=True),a.seconds,a.slice),indent=2))

