"""Offline global endpoint proofs, with a compact exact fallback and scoped hints."""
import argparse
import gzip
import hashlib
import json
import math
import random
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from time import perf_counter

from ortools.sat.python import cp_model
from .. import terminal_exact
from ..solver import read_witness
from . import age_network, flow_price, gate_projection
from .boundary_campaign import ARCHIVE, ORDER, OUTPUT, atomic, initialize, upper
from .frontier_witness import unpack, lift
from .target_queries import digest, load, record_plan

DEST=Path("results/local/upper-campaign-010")
PRIORITY=("blind-16-h-f2","blind-16-h-f3")


def compact(p,domain,q,parts,plan,seed,neighborhood):
    jobs,P,L,d=domain
    S=P+L+2*d
    bundle=terminal_exact.build(p,domain,q)
    model=bundle.model
    model.clear_objective()
    model.add(bundle.repair_variable==q)
    moves=bundle.tasks
    incoming=moves[::2]
    outgoing=moves[1::2]
    last_time=model.new_int_var(0,max(j.due for j in jobs)-P,"last_pick")
    model.add_max_equality(last_time,[m["pick_start"] for m in incoming])
    last=[]
    precedes=[]
    occupancy={}
    for i,j in enumerate(jobs):
        a,b,z=incoming[i]["pick_start"],incoming[i]["place_start"],outgoing[i]["pick_start"]
        islast=model.new_bool_var("last")
        model.add(a==last_time).only_enforce_if(islast)
        model.add(a<last_time).only_enforce_if(~islast)
        last.append(islast)
        before=model.new_bool_var("before_last")
        model.add(z+S<=last_time).only_enforce_if(before)
        model.add(z>=last_time+S).only_enforce_if(~before)
        precedes.append(before)
        # Virtual occupancy [b-P-d,z+S) is disjoint on a single chamber:
        # a following inbound cannot start until the preceding robot cycle ends.
        span=model.new_int_var(1,j.hold_in+max(t for _,t in j.choices)+j.residence+3*S,"chamber_span")
        model.add(span==z+S-b+P+d)
        for c,t in j.choices:
            selected=model.new_bool_var("assigned")
            target=bundle.locations.index(c)
            model.add(incoming[i]["destination"]==target).only_enforce_if(selected)
            model.add(incoming[i]["destination"]!=target).only_enforce_if(~selected)
            occupancy.setdefault(c,[]).append(model.new_optional_interval_var(b-P-d,span,z+S,selected,"turnaround"))
    model.add_exactly_one(last)
    for intervals in occupancy.values(): model.add_no_overlap(intervals)
    rank=len(jobs)-1+sum(precedes)
    first=min(max(0,j.ready,0 if j.source==p.snapshot["robot"]["position"] else d) for j in jobs)
    model.add(last_time>=first+rank*S)
    selectors=[]
    for part in parts:
        if part["upper"]<q: continue
        on=model.new_bool_var("retained_partition")
        selectors.append(on)
        model.add(rank==part["rank"]).only_enforce_if(on)
        if part["job"] is not None: model.add(last[part["job"]]==1).only_enforce_if(on)
        for i,c in part["route"]:
            model.add(incoming[i]["destination"]==bundle.locations.index(c)).only_enforce_if(on)
    model.add_exactly_one(selectors)
    seq,cs=unpack(domain,plan)
    byjob={j.wafer:i for i,j in enumerate(jobs)}
    for row in plan["transfers"]:
        i=byjob[row["wafer_id"]]
        m=moves[2*i+int(row["destination"]=="OUT")]
        model.add_hint(m["pick_start"],row["pick_start"])
        if row["destination"]!="OUT":
            model.add_hint(m["place_start"],row["place_start"])
            model.add_hint(m["destination"],bundle.locations.index(cs[i]))
    if neighborhood:
        rng=random.Random(seed)
        free=set(rng.sample(range(len(jobs)),max(3,len(jobs)//3)))
        anchors=[m for m in seq if m//2 not in free]
        for m,k in zip(anchors,anchors[1:]):
            model.add(moves[m]["place_end"]+d<=moves[k]["pick_start"])
    return bundle


def solve_model(model,until,folder,seed,workers,objective=False):
    s=cp_model.CpSolver()
    s.parameters.num_search_workers=workers
    s.parameters.random_seed=seed
    s.parameters.max_time_in_seconds=max(0,until-perf_counter())
    bounds=[]
    if objective:
        s.best_bound_callback=lambda u: bounds.append(u) if math.isfinite(u) else None
    status=s.solve(model)
    if status==cp_model.MODEL_INVALID: raise ValueError(model.validate())
    rec=dict(status=s.status_name(status),seconds=s.wall_time,branches=s.num_branches,
             conflicts=s.num_conflicts,variables=len(model.proto.variables),
             constraints=len(model.proto.constraints),response_bound=s.best_objective_bound,
             solver_limit=s.parameters.max_time_in_seconds,workers=workers,seed=seed,bound_events=bounds)
    (folder/"response.pb").write_bytes(s.response_proto.SerializeToString())
    return rec,s


def snapshot_model(model,folder,row):
    raw=model.proto.SerializeToString(deterministic=True)
    path=folder/"model.pb.gz"
    path.write_bytes(gzip.compress(raw,compresslevel=1))
    row.update(file=str(path),model_sha256=hashlib.sha256(raw).hexdigest())


def decide(history,lo,hi,priority):
    # All proof arms cover the full equipment state. A failed witness-only
    # neighborhood cannot lower the bound. Finer grids follow coarse failures.
    idx=len(history)
    pattern=("projection_max","flow","endpoint","flow","neighborhood","projection_fixed","flow","endpoint")
    if not priority:
        pattern=("flow","projection_max","flow","projection_fixed","endpoint","flow","neighborhood")
    method=pattern[idx%len(pattern)]
    if method=="projection_max":
        return method,lo,None
    tried=[r for r in history if r["tool"]==method]
    # Attack an interior point on wide gaps, reserve the easier upper endpoint
    # after an inconclusive interior attempt. Proved lo/hi always take priority.
    gap=hi-lo
    target=hi
    if gap>=16 and method in ("flow","projection_fixed") and len(tried)%3!=1:
        target=lo+max(1,math.ceil(gap*(0.55 if len(tried)%3==0 else 0.80)))
    if method=="endpoint" and len(tried)%3==2:
        target=lo+(gap+1)//2
    if method=="flow":
        for quantum in (6,3,2):
            if not any(r["q"]==target and r.get("quantum")==quantum for r in tried):
                return method,target,quantum
        method="endpoint"
    return method,target,None


def action(job,inputs,history,folder,end,priority):
    case,p,h,domain=inputs
    lo,hi=job["lower"],upper(job)
    method,q,grid=decide(history,lo,hi,priority)
    seed=19117+len(history)
    start=perf_counter()
    row=dict(tool=method,q=q,old=[lo,hi])
    newhi=hi
    plan=None
    if method=="flow":
        S=domain[1]+domain[2]+2*domain[3]
        chambers={c for j in domain[0] for c,_ in j.choices}
        if S%grid or len(chambers)>3:
            method="projection_fixed"
            row["tool"]=method
    if method=="flow":
        bounds,table,size=age_network.matrix(domain,grid,repair=q,failed=p.failed_chamber,singleton=True)
        build_seconds=perf_counter()-start
        proof=flow_price.solve_table(bounds,table,end)
        row.update(quantum=grid,graph=size,objective=proof.get("objective"),lp_status=proof.get("lp_status"),
                   build_seconds=build_seconds,status=proof["status"])
        if proof["status"]=="INFEASIBLE":
            num=flow_price.rational_lower(bounds,table,proof["prices"],proof["denominator"])
            if num!=proof["numerator"] or num<=0: raise ValueError("Unverified dual")
            atomic(folder/"dual.json",proof)
            row.update(file=str(folder/"dual.json"),numerator=num,denominator=proof["denominator"])
            newhi=q-1
    elif method.startswith("projection"):
        model,v=gate_projection.build(p,domain,q,hi)
        optimize=method=="projection_max"
        if optimize: model.maximize(v)
        row["build_seconds"]=perf_counter()-start
        info,s=solve_model(model,end,folder,seed,6,optimize)
        row.update(info)
        if info["status"]=="INFEASIBLE":
            newhi=q-1
        elif optimize:
            valid=info["bound_events"][:]
            if info["status"] in ("FEASIBLE","OPTIMAL"): valid.append(s.best_objective_bound)
            if valid: newhi=min(hi,math.ceil(min(valid)))
        if newhi<hi: snapshot_model(model,folder,row)
    else:
        local=method=="neighborhood"
        bundle=compact(p,domain,q,job["parts"],load(Path(job["witness"])),seed,local)
        row["build_seconds"]=perf_counter()-start
        info,s=solve_model(bundle.model,end,folder,seed,6)
        row.update(info)
        if info["status"] in ("FEASIBLE","OPTIMAL"):
            plan,check=read_witness(p,bundle,s,q/p.scale)
            if not check["valid"]: raise ValueError(check["errors"])
            seq,cs=unpack(domain,plan)
            hit=lift(p,domain,seq,cs,q,hi)
            if hit is None: raise ValueError("Cannot retime witness")
            q,plan=hit
        elif info["status"]=="INFEASIBLE" and not local:
            newhi=q-1
            snapshot_model(bundle.model,folder,row)
    if plan:
        achieved=record_plan(case,p,h,q,plan,folder/"witness")
        tick=round(achieved*p.scale)
        if not lo<tick<=hi: raise ValueError("Witness crossed prior bounds")
        job.update(lower=tick,witness=str(folder/"witness"/"schedule.json"))
        row["witness"]=job["witness"]
    if newhi<job["lower"]: raise ValueError("Contradiction with verified schedule")
    for part in job["parts"]: part["upper"]=min(part["upper"],newhi)
    job["parts"]=[n for n in job["parts"] if n["upper"]>job["lower"]]
    job["turns"]+=1
    row.update(after=[job["lower"],upper(job)],wall=perf_counter()-start)
    return row


def run(out,seconds):
    out.mkdir(parents=True,exist_ok=True)
    lock=sqlite3.connect(out/"writer.sqlite",timeout=0,isolation_level=None)
    try:
        lock.execute("BEGIN IMMEDIATE")
        seed=out/"before.json"
        if not seed.exists(): shutil.copyfile(OUTPUT/"state.json",seed)
        if digest(seed)!=digest(OUTPUT/"state.json"): raise ValueError("Prior checkpoint changed")
        file=out/"state.json"
        if not file.exists(): shutil.copyfile(seed,file)
        state,inputs=initialize(ARCHIVE,out,ORDER.resolve())
        binding=[digest(seed),digest(Path(__file__)),digest(Path(gate_projection.__file__))]
        if state.get("upper_binding",binding)!=binding: raise ValueError("Upper study changed")
        state["upper_binding"]=binding
        rows=state.setdefault("upper_actions",[])
        jobs=state["jobs"]
        spent=Counter()
        for row in rows: spent[row["case"]]+=row["wall"]
        start=perf_counter()
        end=start+seconds
        while perf_counter()<end:
            active=[n for n,j in jobs.items() if upper(j)>j["lower"]]
            if not active: break
            def weight(n): return 3 if n in PRIORITY else 1
            name=min(active,key=lambda n:(spent[n]/weight(n),n not in PRIORITY,n))
            hist=[r for r in rows if r["case"]==name]
            folder=out/"steps"/f"{len(rows):04}-{name}"
            folder.mkdir(parents=True,exist_ok=True)
            dt=25 if len(hist)<5 else 40
            if name not in PRIORITY: dt=min(dt,22)
            row=action(jobs[name],inputs[name],hist,folder,min(end,perf_counter()+dt),name in PRIORITY)
            row["case"]=name
            rows.append(row)
            spent[name]+=row["wall"]
            atomic(file,state)
            print(name,row["tool"],row["q"],row["status"],row["after"],flush=True)
        atomic(out/"summary.json",dict(search_seconds=perf_counter()-start,budget=seconds,
            records=len(rows),cases={n:dict(lower=j["lower"]/j["scale"],upper=upper(j)/j["scale"],
            time_seconds=spent[n],witness=j["witness"],status="FINITE" if j["lower"]==upper(j) else "UNKNOWN")
            for n,j in jobs.items()}))
    finally:
        lock.close()

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path,default=DEST)
    ap.add_argument("--seconds",type=float,default=1800)
    a=ap.parse_args()
    run(a.out,a.seconds)

