"""Refine only an unresolved last-rank partition by the identity of its final inbound wafer."""
import argparse
import gzip
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from ortools.sat.python import cp_model
from .target_queries import Continuation,load,save,digest,record_plan,terminal_domain
from . import slot_query
from .frontier_witness import lift


def submodel(problem,domain,q,k,i):
    model,opts,idle,held=slot_query.build(problem,domain,q,k)
    slot_query.add_gap_cuts(model,domain,k,opts,idle,held)
    jobs,P,L,d=domain
    model.add_exactly_one(x for j,c,u,v,x in opts if j==i and u==k)
    model.add(idle[k]+k*(P+L+2*d)+P<=jobs[i].due)
    return model,opts


def investigate(src,original,out,seconds):
    out.mkdir(parents=True,exist_ok=False)
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    domain=terminal_domain(p)
    prior=load(original/"result.json")
    assert prior["snapshot"]==digest(src)
    q=prior["tick"]
    trace=[]
    lower=None
    for k in slot_query.ranks(domain):
        parent=next(t for t in prior["partitions"] if t["last"]==k)
        if parent["status"]=="INFEASIBLE":
            data=gzip.decompress((original/f"last-{k}.pb.gz").read_bytes())
            assert sha256(data).hexdigest()==prior["model_sha256"][str(k)]
            assert slot_query.build(p,domain,q,k)[0].proto.SerializeToString(deterministic=True)==data
            trace.append(dict(rank=k,status="INFEASIBLE",source=str(original/"result.json")))
            continue
        for i,job in enumerate(domain[0]):
            model,opts=submodel(p,domain,q,k,i)
            data=model.proto.SerializeToString(deterministic=True)
            dest=out/f"rank-{k}-job-{i}.pb.gz"
            dest.write_bytes(gzip.compress(data,compresslevel=1))
            s=cp_model.CpSolver()
            s.parameters.num_search_workers=3
            s.parameters.max_time_in_seconds=seconds
            status=s.solve(model)
            if status==cp_model.MODEL_INVALID: raise ValueError(model.validate())
            trace.append(dict(rank=k,index=i,wafer=job.wafer,status=s.status_name(status),
                              seconds=s.wall_time,model_sha256=sha256(data).hexdigest()))
            if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
                n=len(domain[0])
                seq=[None]*(2*n); cs=[None]*n
                for j,c,u,v,x in opts:
                    if s.boolean_value(x):
                        seq[u],seq[v],cs[j]=2*j,2*j+1,c
                hit=lift(p,domain,seq,cs,q,q)
                assert hit
                lower=record_plan(case,p,h,q,hit[1],out)
                break
        if lower is not None: break
    proved=bool(trace) and all(t["status"]=="INFEASIBLE" for t in trace)
    status="FEASIBLE" if lower is not None else "INFEASIBLE" if proved else "UNKNOWN"
    save(out/"result.json",dict(case=src.stem,snapshot=digest(src),status=status,tick=q,lower=lower,
          subpartitions=trace,per_solver_seconds=seconds))
    return status,lower


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("src","original","out"): ap.add_argument("--"+k,type=Path,required=True)
    ap.add_argument("--seconds",type=float,default=12)
    a=ap.parse_args()
    print(investigate(a.src,a.original,a.out,a.seconds))

