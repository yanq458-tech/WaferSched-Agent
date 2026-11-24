"""Recheck frozen runs and publish paired endpoints and real planning decisions."""
import argparse
import csv
from collections import Counter
from pathlib import Path
from hashlib import sha256
import json

from review_learned_recovery import classify, delta, endpoint, why
from wafer_sched.recovery import holdout
from wafer_sched.recovery.conflict_evidence import verify_bound
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.evidence_study import save
from wafer_sched.recovery.feedback.audit import replay
from wafer_sched.recovery.feedback.learned_study import conflict_check, read


def decisions(record):
    trace = record["raw"]["trace"]
    for i,event in enumerate(trace):
        if event["tool"] != "value_query":
            continue
        receipts = []
        for next_event in trace[i+1:]:
            if next_event["tool"] == "value_query":
                break
            if next_event["tool"] in ("grid_satisfaction","strengthened_fixed_repair"):
                receipts.append([next_event.get("repair_tick"),next_event["status"]])
        yield dict(case=record["case"],budget=record["budget"],repeat=record["rep"],**event,receipts=receipts)


def review(root):
    for file,digest in read(root/"freeze.json").items():
        if holdout.digest(root/file)!=digest:
            raise ValueError(f"Frozen input changed: {file}")
    rows,forecasts=[],[]
    witnessed,certified=set(),set()
    occurrences=0
    for item in read(root/"manifest.json"):
        name=item["case"]
        path=root/"inputs"/(name+".json")
        assert holdout.digest(path)==item["sha256"]
        case=Continuation.from_dict(read(path))
        problem,_=case.prepare()
        lows,caps=[],[]
        zero=False
        for b in (1,30):
            for rep in (0,1):
                batch={}
                for arm in ("human","learned","value"):
                    record=read(root/"runs"/str(b)/name/f"{rep}-{arm}.json")
                    assert (record["arm"],record["case"],record["budget"],record["rep"])==(arm,name,b,rep)
                    raw=record["raw"]
                    late=record["wall"]>b
                    assert record["late"]==late
                    assert record["status"]==("UNKNOWN" if late else raw["status"])
                    if late:
                        assert record["lower"] is None and record["upper"] is None
                    plan=(raw.get("best") or {}).get("schedule")
                    if plan:
                        occurrences+=1
                        delay=raw["witness_repair_delay_seconds"]
                        key=(name,delay,sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest())
                        if key not in witnessed:
                            replay(case,plan,delay)
                            witnessed.add(key)
                        lows.append(delay)
                    if raw.get("finite_upper_seconds") is not None:
                        caps.append(raw["finite_upper_seconds"])
                    if raw["status"]=="INFEASIBLE_AT_ZERO":
                        zero=True
                    cert=raw.get("certificate")
                    if cert:
                        key=name,json.dumps(cert,sort_keys=True)
                        if key not in certified:
                            if cert["kind"] in ("exclusive_terminal_deadlines","terminal_capacity_workload","terminal_pending_residence"):
                                assert conflict_check(problem,cert)
                            else:
                                assert verify_bound(problem,cert)
                            certified.add(key)
                    if arm=="value":
                        forecasts.extend(decisions(record))
                    batch[arm]=record
                v=batch["value"]
                for base in ("human","learned"):
                    h=batch[base]
                    rows.append(dict(case=name,budget=b,repeat=rep,baseline=base,result=classify(h,v),
                        baseline_interval=endpoint(h),value_interval=endpoint(v),
                        baseline_status=h["status"],value_status=v["status"],baseline_late=h["late"],value_late=v["late"],
                        baseline_lower=h["lower"],baseline_upper=h["upper"],value_lower=v["lower"],value_upper=v["upper"],
                        lower_gain=delta(v["lower"],h["lower"]),upper_gain=delta(h["upper"],v["upper"]),
                        gap_reduction=delta(delta(h["upper"],h["lower"]),delta(v["upper"],v["lower"])),
                        baseline_wall=h["wall"],value_wall=v["wall"],baseline_reason=why(h),value_reason=why(v)))
        assert not lows or not caps or max(lows)<=min(caps)
        assert not zero or not lows
    with (root/"paired.csv").open("w",newline="",encoding="utf-8-sig") as out:
        writer=csv.DictWriter(out,fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    save(root/"decisions.json",forecasts)
    summary=[]
    for base in ("human","learned"):
        for b in (1,30):
            for rep in (0,1):
                rs=[r for r in rows if (r["baseline"],r["budget"],r["repeat"])==(base,b,rep)]
                summary.append(dict(baseline=base,budget=b,repeat=rep,
                    base_proofs=sum(r["baseline_status"]!="UNKNOWN" for r in rs),
                    value_proofs=sum(r["value_status"]!="UNKNOWN" for r in rs),
                    base_late=sum(r["baseline_late"] for r in rs),value_late=sum(r["value_late"] for r in rs),
                    cases={key:[r["case"] for r in rs if r["result"]==key] for key in sorted({r["result"] for r in rs})}))
    free=[r for r in forecasts if len(set(r["candidates"].values()))==2]
    save(root/"audit.json",dict(runs=3*len(rows)//2,witness_occurrences=occurrences,distinct_replayed=len(witnessed),
        distinct_checked_certificates=len(certified),policy_calls=len(forecasts),two_distinct_choices=len(free),
        freely_chosen=dict(Counter(r["chosen"] for r in free)),
        different_from_default=sum(r["tick"]!=r["default_tick"] for r in forecasts),summary=summary))
    md=["# 新快照上的逐例收益与退步","","编号标识本轮新种子。单位为故障后秒数。问号表示没有已验证见证，不能用零代替。"]
    for base in ("human","learned"):
        for rep in (0,1):
            for b in (1,30):
                md.extend(["",f"## 相对{'人工策略' if base=='human' else '上一版学习策略'} · {b} 秒 · "+("首轮" if rep==0 else "反序"),
                           "","|快照|基线|新版|下界提高|上界降低|区间缩小|结果|","|---|---|---|---:|---:|---:|---|"])
                for r in rows:
                    if (r["baseline"],r["repeat"],r["budget"])==(base,rep,b):
                        cols=[r[k] for k in ("case","baseline_interval","value_interval","lower_gain","upper_gain","gap_reduction","result")]
                        md.append("|"+"|".join("—" if x is None else str(x) for x in cols)+"|")
    (root/"cases.md").write_text("\n".join(md)+"\n",encoding="utf-8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    review(parser.parse_args().root)
