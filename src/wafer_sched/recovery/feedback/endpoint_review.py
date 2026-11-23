"""Verify the queried tick and its tighter bounds, and report each previously missed one-second proof."""
import argparse
import gzip
from hashlib import sha256
from pathlib import Path
from ortools.sat.python import cp_model
from . import slot_query,last_job_probe
from .target_queries import load,save,digest,Continuation,terminal_domain,record_plan
from .branch_results import compare
from ..policy_retest import write_csv,PROVED

def rebuild(folder,path,expected,model):
    data=gzip.decompress((folder/path).read_bytes())
    assert sha256(data).hexdigest()==expected and model.proto.SerializeToString(deterministic=True)==data
    return data


def verify(previous,out,seconds):
    name="blind-16-h-f1"
    src=previous/"inputs"/(name+".json")
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    dom=terminal_domain(p)
    assert p.scale==8 and h["offset"]==0
    original=previous/"certificates"/name
    assert load(original/"ledger.json")["snapshot"]==digest(src)
    assert load(out/"retained/schedule.json")==load(original/"schedule.json")
    assert record_plan(case,p,h,67,load(original/"schedule.json"),out/"retained")==8.375
    evidenced=[]
    receipts=[]
    witnesses=[]
    folders=[out/"slot"/name,*sorted(out.glob("probe-*/slot/"+name))]
    for folder in folders:
        row=load(folder/"result.json")
        assert row["snapshot"]==digest(src)
        ks=list(slot_query.ranks(dom))
        if row["status"]=="INFEASIBLE":
            assert [x["last"] for x in row["partitions"]]==ks
            assert all(x["status"]=="INFEASIBLE" for x in row["partitions"])
            evidenced.append((row["tick"],str(folder/"result.json")))
        for part in row["partitions"]:
            k=part["last"]
            model=slot_query.build(p,dom,row["tick"],k)[0]
            rebuild(folder,f"last-{k}.pb.gz",row["model_sha256"][str(k)],model)
            if row["status"]=="INFEASIBLE" and seconds:
                solver=cp_model.CpSolver()
                solver.parameters.random_seed=11
                solver.parameters.num_search_workers=4
                solver.parameters.max_time_in_seconds=seconds
                st=solver.solve(model)
                assert st in (cp_model.INFEASIBLE,cp_model.UNKNOWN)
                receipts.append(dict(tick=row["tick"],rank=k,status=solver.status_name(st),seconds=solver.wall_time))
    for folder in sorted(out.glob("last-job-*")):
        row=load(folder/"result.json")
        assert row["snapshot"]==digest(src)
        trace=row["subpartitions"]
        if row["status"]=="INFEASIBLE":
            for k in slot_query.ranks(dom):
                parts=[x for x in trace if x["rank"]==k]
                if len(parts)==1 and "source" in parts[0]:
                    origin=Path(parts[0]["source"])
                    parent=load(origin)
                    assert origin.parent in folders and parent["tick"]==row["tick"]
                    assert any(t["last"]==k and t["status"]=="INFEASIBLE" for t in parent["partitions"])
                else:
                    assert [x["index"] for x in parts]==list(range(len(dom[0])))
                    for t in parts:
                        i=t["index"]
                        model,_=last_job_probe.submodel(p,dom,row["tick"],k,i)
                        rebuild(folder,f"rank-{k}-job-{i}.pb.gz",t["model_sha256"],model)
                assert all(x["status"]=="INFEASIBLE" for x in parts)
            evidenced.append((row["tick"],str(folder/"result.json")))
    for f in out.rglob("schedule.json"):
        if f.parent.name=="retained": continue
        row=load(f.parent/"result.json")
        assert row["snapshot"]==digest(src)
        assert row["lower"]==record_plan(case,p,h,row["tick"],load(f),f.parent)
        witnesses.append(str(f))
    history=load(original/'ledger.json')
    tick,source=min(evidenced+[(1+round(history['upper']*p.scale),history['evidence'])])
    closed=previous/"certificates/blind-20-h-f3/ledger.json"
    z=load(closed)
    assert z["status"]=="INFEASIBLE_AT_ZERO"
    save(out/"verified.json",dict(immediate_status=z["status"],immediate_case=z["case"],
        previous_immediate_evidence=z["evidence"],rank_snapshot=digest(src),rank_query_tick=tick,
        rank_scale=p.scale,rank_source=source,all_exclusions=evidenced,independent_reruns=receipts,
        additional_witnesses=witnesses,retained_seconds=8.375))


def diagnose(root,previous):
    rows=[]
    for f in sorted(previous.glob("b1/*/*-gap_cuts.json")):
        old=load(f)
        m=old["metrics"]
        if m["status"] in PROVED or "-m-" not in old["case"]: continue
        phases=old["phases"]
        suffix=m["first_suffix_witness_seconds"]
        if m["raw_status"] in PROVED and m["late"] and suffix is not None and suffix<=1:
            reason="deadline_after_suffix_replay"
        elif suffix is None and not old["evidence"]["raw_verified"]:
            reason="no_verified_witness"
        else:
            reason="other"
        n,rep=old["case"],old["repeat"]
        now=load(root/"b1"/n/f"{rep}-fast_grid.json")
        rows.append(dict(case=n,repeat=rep,previous_status=m["raw_status"],classification=reason,
            previous_wall=m["wall_seconds"],previous_grid=phases.get("grid_search",0),
            previous_build=phases.get("build",0),previous_cp=phases.get("cp_sat",0),
            previous_suffix=phases.get("suffix_replay",0),previous_full=phases.get("full_replay",0),
            previous_suffix_finished=suffix,now_status=now["metrics"]["status"],now_wall=now["metrics"]["wall_seconds"],
            now_grid=now["phases"].get("compiled_grid",0),now_suffix=now["phases"].get("suffix_replay",0),
            now_full=now["phases"].get("full_replay",0)))
    write_csv(root/"one-second-diagnosis.csv",rows)

def probe(previous,out,executable):
    """The study's fixed targeted queries are kept out of the timed policy."""
    from . import target_queries,order_probe,order_neighborhood
    name="blind-16-h-f1"
    src=previous/"inputs"/(name+".json")
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    dom=terminal_domain(p)
    old=previous/"certificates"/name
    retained=out/"retained"
    retained.mkdir(parents=True,exist_ok=False)
    lo=round(record_plan(case,p,h,67,load(old/"schedule.json"),retained)*p.scale)
    hi=round(load(old/"ledger.json")["upper"]*p.scale)
    _,status,lower=target_queries.run(previous/"inputs",out,name,180,hi)
    if status=="FEASIBLE": return
    if status=="INFEASIBLE": hi-=1
    for q in (104,86,77,72):
        if not lo<q<=hi: continue
        folder=out/"construct"/str(q)
        folder.mkdir(parents=True,exist_ok=False)
        hit=order_probe.search(p,dom,q,hi,executable.resolve(),6,7951)
        if hit:
            lo=round(p.scale*record_plan(case,p,h,q,hit[1],folder))
        save(folder/"result.json",dict(case=name,snapshot=digest(src),tick=q,
            status="FEASIBLE" if hit else "UNKNOWN",lower=lo/p.scale if hit else None))
    for q,seconds in ((128,100),(114,100),(136,156)):
        if not lo<q<=hi: continue
        _,status,lower=target_queries.run(previous/"inputs",out/f"probe-{q}",name,seconds,q)
        if lower is not None: lo=max(lo,round(p.scale*lower))
        if status=="INFEASIBLE": hi=q-1
    parent=out/"probe-128"/"slot"/name
    if (parent/"result.json").exists() and load(parent/"result.json")["status"]=="UNKNOWN":
        last_job_probe.investigate(src,parent,out/"last-job-128",12)
    if lo<96<=hi:
        order_neighborhood.run(src,out/"neighborhood-96",executable,96,hi,80)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("root","previous","artifacts"): ap.add_argument("--"+k,type=Path,required=True)
    ap.add_argument("--seconds",type=float,default=60)
    ap.add_argument("--probe",action="store_true")
    ap.add_argument("--executable",type=Path)
    a=ap.parse_args()
    if a.probe:
        if a.executable is None: ap.error("--probe requires --executable")
        probe(a.previous,a.artifacts,a.executable)
        raise SystemExit
    verify(a.previous,a.artifacts,a.seconds)
    diagnose(a.root,a.previous)
    print([(r["case"],r["status"],r["lower"],r["upper"]) for r in compare(a.root,a.previous,a.artifacts)])

