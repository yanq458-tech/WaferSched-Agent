"""Offline fixed-route diagnosis. Restricted infeasibility is reported only for the named branch."""
import argparse
import gzip
import hashlib
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from ortools.sat.python import cp_model
from .target_queries import Continuation, load, save, digest, record_plan, terminal_domain
from . import age_flow, order_probe, slot_query

def restrict(domain,wafer,chamber):
    jobs=domain[0]
    matches=[j for j in jobs if j.wafer==wafer]
    if len(matches)!=1 or chamber not in dict(matches[0].choices):
        raise ValueError("Invalid terminal assignment")
    return ([replace(j,choices=((chamber,dict(j.choices)[chamber]),)) if j.wafer==wafer else j for j in jobs],*domain[1:])

def validated_scope(root,directory):
    """Bind last round's checked complementary proof to the identical input and model."""
    from unittest.mock import patch
    from .capacity import bound
    row=load(directory/"result.json")
    receipt,=load(directory/"route-proof.json")
    name=row["case"]
    src=root/"inputs"/(name+".json")
    assert digest(src)==row["snapshot"]==receipt["snapshot"]
    assert receipt["status"]=="INFEASIBLE" and receipt["repair_tick"]==row["tick"]==0
    w=row["wafer"]
    excluded=receipt["destination"]
    assert receipt["wafer"]==w
    assert any(b["chamber"]==excluded and b["status"]=="INFEASIBLE" for b in row["branches"])
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    assert h["offset"]==0
    dom=terminal_domain(p)
    job,=[j for j in dom[0] if j.wafer==w]
    remaining,=[c for c,t in job.choices if c!=excluded]
    data=gzip.decompress((directory/("route-"+excluded+".pb.gz")).read_bytes())
    assert hashlib.sha256(data).hexdigest()==receipt["model_sha256"]
    # Reconstruct bytes only. No new search on the excluded route.
    class Rebuilt(Exception): pass
    def canonical(proto):
        # The old archive iterated a set of chamber names; conjunction and term order are immaterial.
        cp=type(proto)()
        cp.CopyFrom(proto)
        for row in cp.constraints:
            if row.HasField("linear"):
                terms=sorted(zip(row.linear.vars,row.linear.coeffs))
                row.linear.vars[:]=[v for v,k in terms]
                row.linear.coeffs[:]=[k for v,k in terms]
        rows=sorted(r.SerializeToString(deterministic=True) for r in cp.constraints)
        del cp.constraints[:]
        return cp.SerializeToString(deterministic=True),rows
    def compare(solver,model):
        prior=cp_model.CpModel()
        prior.proto.ParseFromString(data)
        assert canonical(model.proto)==canonical(prior.proto)
        raise Rebuilt
    with patch.object(cp_model.CpSolver,"solve",compare):
        try:
            bound(p,restrict(dom,w,excluded),0,perf_counter()+1,endpoints=True,prefix_split=True,threshold=0)
        except Rebuilt:
            pass
        else:
            raise ValueError("Complementary model was not rebuilt")
    return name,dict(wafer=w,chamber=remaining,excluded=excluded,receipt=digest(directory/"route-proof.json"))

def probe(src,out,wafer,chamber,q,tool,budget,quantum=6,exe=None):
    out.mkdir(parents=True,exist_ok=False)
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    dom=terminal_domain(p)
    if wafer: dom=restrict(dom,wafer,chamber)
    info=dict(case=src.stem,snapshot=digest(src),wafer=wafer,chamber=chamber,tick=q,scale=p.scale,
              tool=tool,budget=budget)
    start=perf_counter()
    plan=None
    def export(name,model):
        data=model.proto.SerializeToString(deterministic=True)
        (out/(name+".pb.gz")).write_bytes(gzip.compress(data,compresslevel=1))
        info.setdefault("hashes",{})[name]=hashlib.sha256(data).hexdigest()
    if tool=="flow":
        if q!=0: raise ValueError("Immediate repair only")
        model,more=age_flow.build(dom,quantum)
        export("age-flow",model)
        solver=cp_model.CpSolver()
        solver.parameters.num_search_workers=4
        solver.parameters.max_time_in_seconds=max(0,start+budget-perf_counter())
        status=solver.solve(model)
        if status==cp_model.MODEL_INVALID: raise ValueError(model.validate())
        info.update(more,solver=solver.status_name(status),branches=solver.num_branches)
        verdict="INFEASIBLE" if status==cp_model.INFEASIBLE else "UNKNOWN"
    elif tool=="rank":
        verdict,plan,trace=slot_query.query(p,dom,q,start+budget,workers=4,enhanced=True,
                            export=lambda k,m:export("rank-"+str(k),m))
        info["partitions"]=trace
    else:
        runs=[]
        verdict="UNKNOWN"
        while perf_counter()<start+budget:
            seed=7907+len(runs)*977
            result=order_probe.search(p,dom,q,q,exe.resolve(),min(2.8,start+budget-perf_counter()),seed)
            runs.append(seed)
            if result:
                plan=result[1]
                verdict="FEASIBLE"
                break
        info["seeds"]=runs
    if plan:
        if wafer:
            assert any(t["wafer_id"]==wafer and t["destination"]==chamber for t in plan["transfers"])
        info["lower"]=record_plan(case,p,h,q,plan,out)
    info.update(status=verdict,elapsed=perf_counter()-start)
    save(out/"result.json",info)
    print(info,flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("src","out"): ap.add_argument("--"+k,type=Path,required=True)
    ap.add_argument("--wafer")
    ap.add_argument("--chamber")
    ap.add_argument("--tick",type=int,default=0)
    ap.add_argument("--tool",choices=("flow","rank","order"),required=True)
    ap.add_argument("--budget",type=float,default=90)
    ap.add_argument("--quantum",type=int,default=6)
    ap.add_argument("--exe",type=Path)
    a=ap.parse_args()
    probe(a.src,a.out,a.wafer,a.chamber,a.tick,a.tool,a.budget,a.quantum,a.exe)

