"""Targeted offline diagnosis; schedules are replayed at the requested delay itself."""

import argparse
import gzip
import hashlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

from ..continuation import Continuation
from ..dispatch import replay_incident
from ..evidence_study import save
from ..holdout import digest
from ..holdout_review import load
from ..replay import replay_recovery
from ..terminal_exact import terminal_domain
from .slot_query import query

TARGETS={"blind-20-h-f3":0,"blind-24-h-f1":0,"blind-24-h-f2":0,"blind-16-h-f1":173}


def record_plan(case,p,h,q,plan,out):
    gate=min(t["place_start"] for t in plan["transfers"] if t["destination"]==p.failed_chamber)
    assert gate>=q
    for tick in sorted({q,gate}):
        check=replay_recovery(p,tick/p.scale,plan)
        assert check["valid"], check["errors"]
        result=dict(witness_repair_delay_seconds=h["offset"]+tick/p.scale,
                    makespan_seconds=h["offset"]+plan["makespan_tick"]/p.scale)
        replay_incident(case,h,result,dict(verification=check))
        save(out/f"replay-{tick}.json",dict(tick=tick,completed=result["completed_at"],decisions=check["decisions"],
                                           makespan=result["makespan_seconds"]))
    save(out/"schedule.json",plan)
    return h["offset"]+gate/p.scale


def run(src,out,name,seconds,tick=None):
    out=out/"slot"/name
    out.mkdir(parents=True,exist_ok=False)
    path=src/(name+".json")
    case=Continuation.from_dict(load(path))
    p,h=case.prepare()
    q=TARGETS[name] if tick is None else tick
    hashes={}
    def export(k,model):
        data=model.proto.SerializeToString(deterministic=True)
        (out/f"last-{k}.pb.gz").write_bytes(gzip.compress(data,compresslevel=1))
        hashes[str(k)]=hashlib.sha256(data).hexdigest()
    status,plan,trace=query(p,terminal_domain(p),q,perf_counter()+seconds,workers=3,export=export)
    lower=record_plan(case,p,h,q,plan,out) if plan else None
    row=dict(case=name,tick=q,snapshot=digest(path),scale=p.scale,status=status,lower=lower,
             partitions=trace,model_sha256=hashes,budget=seconds)
    save(out/"result.json",row)
    return name,status,lower


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    ap.add_argument("--seconds",default=90,type=float)
    ap.add_argument("--case",choices=list(TARGETS))
    ap.add_argument("--tick",type=int)
    a=ap.parse_args()
    if a.case:
        print(run(a.inputs,a.out,a.case,a.seconds,a.tick))
        raise SystemExit
    if a.tick is not None:
        ap.error("--tick requires --case")
    with ProcessPoolExecutor(max_workers=2) as pool:
        for result in pool.map(run,[a.inputs]*4,[a.out]*4,TARGETS,[a.seconds]*4):
            print(result,flush=True)
