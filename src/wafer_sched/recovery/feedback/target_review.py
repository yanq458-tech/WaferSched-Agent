"""Join matched wall-clock runs and targeted evidence. Recheck input hashes and best schedules."""
import argparse
import gzip
import hashlib
from pathlib import Path
from ..policy_retest import PROVED,write_csv
from .target_queries import Continuation, load, save, digest, record_plan, terminal_domain
from .frontier_evidence import sources
from .slot_query import build,ranks

def review(root,prior,target):
    assert (root/"audit.json").is_file()
    pairs=[]
    for item in sorted(load(root/"manifest.json"),key=lambda r:r["case"]):
        name=item["case"]
        for b in (1,30):
            for path in sorted((root/f"b{b}"/name).glob("*-refined.json")):
                rep=int(path.name.split("-")[0])
                def read(r,m):
                    return load(r/f"b{b}"/name/f"{rep}-{m}.json")
                old,new=read(root,"frontier"),load(path)
                for group,r,m in (("paired_control",root,"frontier"),("previous_run",prior,"frontier")):
                    other=r/f"b{b}"/name/f"{rep}-{m}.json"
                    if not other.exists(): continue
                    baseline=load(other)
                    o,v=baseline["metrics"],new["metrics"]
                    phase=lambda row: sum(row["phases"].get(k,0) for k in ("suffix_replay","full_replay","replay"))
                    pairs.append(dict(case=name,budget=b,repeat=rep,against=group,
                        before=o["status"],after=v["status"],before_raw=o["raw_status"],after_raw=v["raw_status"],
                        proof_gain=int(v["status"] in PROVED)-int(o["status"] in PROVED),
                        before_lower=o["lower"],after_lower=v["lower"],before_upper=o["upper"],after_upper=v["upper"],
                        before_makespan=o["makespan"],after_makespan=v["makespan"],
                        before_wall=o["wall_seconds"],after_wall=v["wall_seconds"],
                        before_replay=phase(baseline) if group=="paired_control" else None,after_replay=phase(new),
                        before_late=o["late"],after_late=v["late"]))
    write_csv(root/"paired-deltas.csv",pairs)
    ledger=[]
    for mem in sorted((root/"memory").glob("*.json")):
        name=mem.stem
        src=root/"inputs"/(name+".json")
        case=Continuation.from_dict(load(src))
        p,h=case.prepare()
        assert h["offset"]==0
        upper,plans=sources(root,None,name)
        for f in target.rglob("result.json"):
            row=load(f)
            if row.get("case")!=name: continue
            assert (row.get("snapshot") or row.get("snapshot_sha256"))==digest(src)
            if row.get("status")=="INFEASIBLE" and "partitions" in row:
                dom=terminal_domain(p)
                assert [t["last"] for t in row["partitions"]]==list(ranks(dom))
                for t in row["partitions"]:
                    k=t["last"]
                    assert t["status"]=="INFEASIBLE"
                    data=gzip.decompress((f.parent/f"last-{k}.pb.gz").read_bytes())
                    assert hashlib.sha256(data).hexdigest()==row["model_sha256"][str(k)]
                    model=build(p,dom,row["tick"],k)[0]
                    assert model.proto.SerializeToString(deterministic=True)==data
                upper.append(((row["tick"]-1)/p.scale,str(f)))
            if row.get("lower") is not None:
                plan=load(f.parent/"schedule.json")
                plans.append((row["lower"],plan["makespan_tick"]/p.scale,plan,str(f)))
        folder=root/"certificates"/name
        folder.mkdir(parents=True,exist_ok=True)
        hi,usrc=min(upper)
        lo=span=wsrc=None
        if plans:
            lo,span,plan,wsrc=min(plans,key=lambda x:(-x[0],x[1]))
            assert lo<=hi
            assert record_plan(case,p,h,0,plan,folder)==lo
        historic=load(prior/"certificates"/name/"ledger.json")
        record=dict(case=name,status="FINITE" if hi==lo else "UNKNOWN",lower=lo,upper=hi,
                previous_lower=historic["lower"],previous_upper=historic["upper"],
                makespan=span,witness_source=wsrc,upper_source=usrc,snapshot=digest(src))
        save(folder/"ledger.json",record)
        ledger.append(record)
    write_csv(root/"ledger.csv",ledger)
    return ledger

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("root","prior","target"):
        ap.add_argument("--"+k,required=True,type=Path)
    a=ap.parse_args()
    for row in review(a.root,a.prior,a.target):
        print(row["case"],row["lower"],row["upper"])

