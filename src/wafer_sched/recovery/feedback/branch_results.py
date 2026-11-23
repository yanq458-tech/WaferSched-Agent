"""Summarize strict-budget paired returns separately from independently established case facts."""
import argparse
from pathlib import Path
from .target_queries import Continuation,load,save,digest,record_plan
from ..policy_retest import PROVED,write_csv

def compare(root,previous,artifacts):
    audit=load(root/"audit.json")
    assert len(audit)==18 and digest(root/"manifest.json")==digest(previous/"manifest.json")
    control,candidate=load(root/"protocol.json")["methods"]
    previous_method=load(previous/"protocol.json")["methods"][-1]
    pair=[]
    intervals=[]
    verified=load(artifacts/"verified.json")
    for item in load(root/"manifest.json"):
        name=item["case"]
        for budget in (1,30):
            folder=root/f"b{budget}"/name
            for f in sorted(folder.glob(f"*-{candidate}.json")):
                rep=int(f.name.split("-")[0])
                run=load(f)["metrics"]
                for label,path in (("same_run",folder/f"{rep}-{control}.json"),
                                   ("previous",previous/f"b{budget}"/name/f"{rep}-{previous_method}.json")):
                    if not path.exists(): continue
                    ref=load(path)["metrics"]
                    one=dict(case=name,budget=budget,repeat=rep,against=label,
                             proof_change=int(run["status"] in PROVED)-int(ref["status"] in PROVED))
                    for k in ("status","raw_status","late","wall_seconds","lower","upper","makespan"):
                        one["old_"+k]=ref[k]
                        one["new_"+k]=run[k]
                    pair.append(one)
        prior=previous/"certificates"/name/"ledger.json"
        if not prior.exists(): continue
        old=load(prior)
        src=root/"inputs"/(name+".json")
        assert digest(src)==item["sha256"]==old["snapshot"]
        case=Continuation.from_dict(load(src))
        p,h=case.prepare()
        assert h["offset"]==0
        receipt=root/"certificates"/name
        receipt.mkdir(parents=True,exist_ok=True)
        if name==verified["immediate_case"]:
            assert verified["immediate_status"]=="INFEASIBLE_AT_ZERO" and old["lower"] is None
            row=dict(case=name,status="INFEASIBLE_AT_ZERO",lower=None,upper=None,
                     evidence=str(artifacts/"verified.json"))
        else:
            upper=[(old["upper"],old.get("upper_source") or old["evidence"])]
            plans=[]
            if old["lower"] is not None:
                prior_schedule=prior.parent/"schedule.json"
                plans.append((old["lower"],old["makespan"],str(prior_schedule),load(prior_schedule)))
            if item["sha256"]==verified["rank_snapshot"]:
                u=(verified["rank_query_tick"]-1)/verified["rank_scale"]
                upper.append((u,verified.get("rank_source") or str(artifacts/"slot"/name/"result.json")))
                for file in verified.get("additional_witnesses",[]):
                    candidate_plan=load(Path(file))
                    gate=min(t["place_start"] for t in candidate_plan["transfers"] if t["destination"]==p.failed_chamber)
                    plans.append((gate/p.scale,candidate_plan["makespan_tick"]/p.scale,file,candidate_plan))
            for f in sorted(root.glob(f"b*/{name}/*.json")):
                run=load(f)
                m,e=run["metrics"],run["evidence"]
                if m["late"]: continue
                if m["upper"] is not None: upper.append((m["upper"],str(f)))
                if e["raw_verified"]:
                    plans.append((e["witness_repair"],e["raw_makespan"],str(f),e["schedule"]))
            hi,proof=min(upper)
            lo,end,witness,plan=min(plans,key=lambda v:(-v[0],v[1]))
            assert lo<=hi and record_plan(case,p,h,0,plan,receipt)==lo
            row=dict(case=name,status="FINITE" if lo==hi else "UNKNOWN",lower=lo,upper=hi,
                     evidence=proof,witness_source=witness,makespan=end)
        row.update(previous_lower=old["lower"],previous_upper=old["upper"],snapshot=item["sha256"])
        save(receipt/"ledger.json",row)
        intervals.append(row)
    write_csv(root/"paired-deltas.csv",pair)
    write_csv(root/"frontiers.csv",[{k:r.get(k) for k in ("case","status","lower","upper",
          "previous_lower","previous_upper","makespan","evidence","witness_source","snapshot")} for r in intervals])
    return intervals

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("root","previous","artifacts"):
        ap.add_argument("--"+k,type=Path,required=True)
    a=ap.parse_args()
    print([(x["case"],x["status"],x["lower"],x["upper"]) for x in compare(a.root,a.previous,a.artifacts)])

