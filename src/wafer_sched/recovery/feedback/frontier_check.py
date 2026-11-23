"""Standalone certificates and off-clock fixed-delay diagnostics using the original inputs."""

import argparse
import gzip
import hashlib
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from ortools.sat.python import cp_model
from ..conflict_evidence import best_bound
from ..continuation import Continuation
from ..dispatch import replay_incident
from ..evidence_study import save
from ..holdout import digest
from ..holdout_review import load
from ..replay import replay_recovery
from ..terminal_exact import terminal_domain
from . import capacity, exact


def check(src,out,tick,seconds,workers=1,kind="capacity"):
    incident=Continuation.from_dict(load(src))
    p,h=incident.prepare()
    domain=terminal_domain(p)
    cap=best_bound(p)["upper_tick"]
    out.mkdir(parents=True,exist_ok=False)
    model_file=out/"model.pb.gz"
    original=cp_model.CpSolver.solve
    meta=dict(snapshot_sha256=digest(src),case=src.stem,scale=p.scale,prefix_offset=h["offset"],
              route_upper=cap,repair_tick=tick,kind=kind,workers=workers,budget=seconds)
    def inspect(s,model,*args,**kwargs):
        payload=model.proto.SerializeToString(deterministic=True)
        meta["model_sha256"]=hashlib.sha256(payload).hexdigest()
        model_file.write_bytes(gzip.compress(payload))
        s.parameters.num_search_workers=workers
        return original(s,model,*args,**kwargs)
    with patch.object(cp_model.CpSolver,"solve",inspect):
        if kind in ("capacity","split","maximize"):
            upper,note=capacity.bound(p,domain,cap,perf_counter()+seconds,endpoints=True,
                                      threshold=None if kind=="maximize" else tick,prefix_split=kind=="split")
            meta.update(status=note["status"],upper_tick=upper,solver=note)
        elif kind=="fixed":
            st,plan,_,note=exact.fixed_query(p,domain,tick,perf_counter()+seconds,seed=7)
            meta.update(status=st,solver=note)
            if plan:
                actual=min(row["place_start"] for row in plan["transfers"] if row["destination"]==p.failed_chamber)
                verified=replay_recovery(p,actual/p.scale,plan)
                assert verified["valid"]
                result=dict(witness_repair_delay_seconds=h["offset"]+actual/p.scale,
                            makespan_seconds=h["offset"]+plan["makespan_tick"]/p.scale)
                replay_incident(incident,h,result,dict(verification=verified))
                save(out/"schedule.json",plan)
                meta.update(verified_lower=result["witness_repair_delay_seconds"],
                            makespan=result["makespan_seconds"],complete_wafers=len(result["completed_at"]))
        else:
            raise ValueError(kind)
    save(out/"result.json",meta)
    return meta


def verify(out,seconds):
    row=load(out/"result.json")
    data=gzip.decompress((out/"model.pb.gz").read_bytes())
    assert hashlib.sha256(data).hexdigest()==row["model_sha256"]
    model=cp_model.CpModel()
    model.proto.ParseFromString(data)
    assert not model.validate()
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=seconds
    solver.parameters.num_search_workers=1
    st=solver.solve(model)
    result=dict(status=solver.status_name(st),branches=solver.num_branches,elapsed=solver.wall_time)
    if row["status"]=="INFEASIBLE" and result["status"] not in ("INFEASIBLE","UNKNOWN"):
        raise ValueError("Contradictory proof")
    save(out/"recheck.json",result)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=["check","verify"])
    ap.add_argument("--src",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--tick",type=int)
    ap.add_argument("--seconds",type=float,default=30)
    ap.add_argument("--workers",type=int,default=1)
    ap.add_argument("--kind",choices=("fixed","capacity","split","maximize"),default="capacity")
    a=ap.parse_args()
    print(check(a.src,a.out,a.tick,a.seconds,a.workers,a.kind) if a.action=="check" else verify(a.out,a.seconds))
