"""Consolidate historical and timed evidence; label extra diagnostic work explicitly."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..continuation import Continuation
from ..dispatch import replay_incident
from ..evidence_study import save
from ..holdout import digest
from ..holdout_review import load
from ..policy_retest import write_csv
from ..replay import replay_recovery
from .frontier_check import check, verify


def sources(root,previous,name):
    mem=load(root/"memory"/(name+".json"))
    bounds=[(mem["upper"],mem["upper_source"])]
    schedules=[]
    if mem["witness"]:
        w=mem["witness"]
        schedules.append((w["witness_repair"],w["makespan"],w["schedule"],w["source"]))
    for study in (previous,root):
        if study is None:
            continue
        assert digest(study/"inputs"/(name+".json"))==mem["snapshot"]
        for f in sorted(study.glob(f"b*/{name}/*.json")):
            run=load(f)
            m,e=run["metrics"],run["evidence"]
            if m["upper"] is not None:
                bounds.append((m["upper"],str(f)))
            if e["raw_verified"]:
                schedules.append((e["witness_repair"],e["raw_makespan"],e["schedule"],str(f)))
    return bounds,schedules


def investigate(root,previous,name):
    folder=root/"certificates"/name
    src=root/"inputs"/(name+".json")
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    offset=h["offset"]
    bounds,schedules=sources(root,previous,name)
    if name=="blind-16-h-f1":
        # The explicit user-requested historical endpoint, read from the frozen archive.
        historical=load(root/"memory"/(name+".json"))["upper"]
        record=check(src,folder/"historical-upper",round((historical-offset)*p.scale),15,2)
        assert record["status"]=="INFEASIBLE"
        verify(folder/"historical-upper",15)
    record=check(src,folder/"maximize",None,25,3,"maximize")
    if record["upper_tick"]>=0 or record["status"]=="INFEASIBLE":
        bounds.append((offset+record["upper_tick"]/p.scale,str(folder/"maximize/result.json")))
    best_upper=min(bounds)[0]
    q=round((best_upper-offset)*p.scale)
    if not schedules:
        # First seek any full witness. Never report a relaxation assignment as one.
        probe=0
    else:
        probe=q
    record=check(src,folder/"full",probe,35,3,"fixed")
    if record.get("verified_lower") is not None:
        schedules.append((record["verified_lower"],record["makespan"],load(folder/"full/schedule.json"),str(folder/"full/result.json")))
    if record["status"]=="INFEASIBLE":
        bounds.append((offset+(probe-1)/p.scale,str(folder/"full/result.json")))
    upper,source=min(bounds)
    if upper>=offset:
        next_tick=round((upper-offset)*p.scale)+1
        confirm=check(src,folder/"next",next_tick,18,3)
        if confirm["status"]=="INFEASIBLE":
            verify(folder/"next",12)
    if schedules:
        lower,makespan,plan,wsrc=min(schedules,key=lambda v:(-v[0],v[1]))
        assert lower<=upper
        v=replay_recovery(p,lower-offset,plan)
        assert v["valid"]
        replay_incident(case,h,dict(witness_repair_delay_seconds=lower,makespan_seconds=makespan),dict(verification=v))
        save(folder/"best-schedule.json",plan)
    else:
        lower=makespan=wsrc=None
    state=("INFEASIBLE_AT_ZERO" if upper<offset else "FINITE" if lower==upper else "UNKNOWN")
    row=dict(case=name,status=state,lower=lower,upper=upper if upper>=offset else None,
             upper_source=source,witness_source=wsrc,makespan=makespan,
             full_query_tick=probe,full_query_status=record["status"])
    save(folder/"ledger.json",row)
    return row


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--previous",type=Path)
    a=ap.parse_args()
    names=sorted(p.stem for p in (a.root/"memory").glob("*.json"))
    with ProcessPoolExecutor(max_workers=3) as pool:
        rows=list(pool.map(investigate,[a.root]*len(names),[a.previous]*len(names),names))
    write_csv(a.root/"ledger.csv",rows)
