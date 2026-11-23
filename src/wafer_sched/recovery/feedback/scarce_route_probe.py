"""Split one wafer's route choices exhaustively, without requiring the scarce chamber to be used."""
import argparse
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from .target_queries import Continuation, terminal_domain, record_plan, load, save, digest
from .capacity import bound
from .slot_query import query

def investigate(src,out,seconds):
    out.mkdir(parents=True,exist_ok=False)
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    domain=terminal_domain(p)
    jobs=domain[0]
    candidates=[j for j in jobs if len(j.choices)>1 and any(
        sum(c in dict(k.choices) for k in jobs)==1 for c,_ in j.choices)]
    job=min(candidates,key=lambda j:j.wafer)
    branches=[]
    witness=None
    for chamber,duration in job.choices:
        subset=([replace(j,choices=((chamber,duration),)) if j==job else j for j in jobs],*domain[1:])
        until=perf_counter()+seconds
        upper,coarse=bound(p,subset,0,min(until,perf_counter()+4),endpoints=True,prefix_split=True,threshold=0)
        trace=[]
        if upper<0:
            status="INFEASIBLE"
        else:
            status,plan,trace=query(p,subset,0,until,workers=3)
            if plan: witness=record_plan(case,p,h,0,plan,out)
        branches.append(dict(chamber=chamber,status=status,relaxation=coarse,partitions=trace))
    status="FEASIBLE" if witness is not None else "INFEASIBLE" if all(b["status"]=="INFEASIBLE" for b in branches) else "UNKNOWN"
    save(out/"result.json",dict(case=src.stem,snapshot=digest(src),wafer=job.wafer,tick=0,
         status=status,lower=witness,branches=branches,seconds_per_branch=seconds))
    return [(b["chamber"],b["status"]) for b in branches]

def recheck(src,out,seconds):
    """Rebuild the assignment relaxation, export its model, and solve the bytes again."""
    import gzip
    from hashlib import sha256
    from unittest.mock import patch
    from ortools.sat.python import cp_model
    row=load(out/"result.json")
    assert row["snapshot"]==digest(src)
    p,_=Continuation.from_dict(load(src)).prepare()
    domain=terminal_domain(p)
    solve=cp_model.CpSolver.solve
    proofs=[]
    for branch in row["branches"]:
        if branch["relaxation"]["status"]!="INFEASIBLE":
            continue
        c=branch["chamber"]
        subset=([replace(j,choices=tuple(ch for ch in j.choices if ch[0]==c))
                 if j.wafer==row["wafer"] else j for j in domain[0]],*domain[1:])
        captured=[]
        def capture(solver,model):
            captured.append(model.proto.SerializeToString(deterministic=True))
            return solve(solver,model)
        with patch.object(cp_model.CpSolver,"solve",capture):
            u,ret=bound(p,subset,0,perf_counter()+seconds,endpoints=True,prefix_split=True,threshold=0)
        assert u==-1 and ret["status"]=="INFEASIBLE"
        binary=out/("route-"+c+".pb.gz")
        binary.write_bytes(gzip.compress(captured[0]))
        data=gzip.decompress(binary.read_bytes())
        fresh=cp_model.CpModel()
        fresh.proto.ParseFromString(data)
        solver=cp_model.CpSolver()
        solver.parameters.num_search_workers=1
        solver.parameters.random_seed=21
        solver.parameters.max_time_in_seconds=seconds
        status=solver.solve(fresh)
        proofs.append(dict(wafer=row["wafer"],destination=c,repair_tick=0,
            status=solver.status_name(status),model_sha256=sha256(data).hexdigest(),snapshot=row["snapshot"]))
        assert status==cp_model.INFEASIBLE
    save(out/"route-proof.json",proofs)
    return proofs


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--seconds",type=int,default=55)
    ap.add_argument("--verify",action="store_true")
    a=ap.parse_args()
    print((recheck if a.verify else investigate)(a.src,a.out,a.seconds))

