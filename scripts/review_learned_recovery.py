"""Audit archived schedules and compare two timed passes; never run a new solver query."""
import argparse
import csv
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.feedback.audit import replay
from wafer_sched.recovery.feedback.learned_study import DEFAULT, read, conflict_check
from wafer_sched.recovery.evidence_study import save


def delta(a, b):
    return None if a is None or b is None else a-b


def classify(h, m):
    hp,mp=h["status"]!="UNKNOWN",m["status"]!="UNKNOWN"
    if hp and mp:
        assert (h["status"],h["lower"])==(m["status"],m["lower"])
        return "同证"
    if hp!=mp:
        return "新增证明" if mp else "丢失证明"
    l1,l2=h["lower"],m["lower"]
    u1,u2=h["upper"],m["upper"]
    signs=[]
    for old,new,direction in ((l1,l2,1),(u1,u2,-1)):
        if old==new: signs.append(0)
        elif old is None: signs.append(1)
        elif new is None: signs.append(-1)
        else: signs.append(direction*(new-old))
    if max(signs)<=0 and min(signs)<0:return "证据退步"
    if min(signs)>=0 and max(signs)>0:return "证据改善"
    return "各有增退" if max(signs)>0 else "持平"


def endpoint(r):
    if r["status"]=="INFEASIBLE_AT_ZERO":return "即修无解"
    if r["status"]=="FINITE":return f'{r["lower"]:g}（精确）'
    lo,hi=r["lower"],r["upper"]
    if lo is None and hi is None:return "无按时边界"
    return f'{lo if lo is not None else "?"}～{hi if hi is not None else "?"}'


def why(r):
    if r["late"]:return "整次返回超时"
    if r["status"]!="UNKNOWN":return r["status"]
    trace=r["raw"]["trace"]
    seen=[v for v in trace if v.get("tool") in ("strengthened_fixed_repair","grid_satisfaction","prefix_capacity_relaxation","terminal_maximize_repair")]
    if not seen:return "尚无探测回执"
    e=seen[-1]
    return f'{e["tool"]} {e.get("status","")}；'+("缺可行见证" if r["lower"] is None else "上下界未合")


def review(root):
    inputs=read(root/"manifest.json")
    rows=[]; witnesses=set(); certs=set(); occurrences=0; decisions=Counter(); policies=Counter(); inference=[]
    for item in inputs:
        name=item["case"]
        case=Continuation.from_dict(read(root/"inputs"/(name+".json")))
        all_records=[]
        for b in (1,30):
            for rep in (0,1):
                h,m=[read(root/"runs"/str(b)/name/f"{rep}-{arm}.json") for arm in ("human","learned")]
                all_records.extend((h,m))
                for r in (h,m):
                    plan=(r["raw"].get("best") or {}).get("schedule")
                    if plan:
                        occurrences+=1
                        delay=r["raw"]["witness_repair_delay_seconds"]
                        key=(name,delay,sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest())
                        if key not in witnesses:
                            replay(case,plan,delay)
                            witnesses.add(key)
                    cert=r["raw"].get("certificate") or {}
                    if cert.get("kind") in ("exclusive_terminal_deadlines","terminal_capacity_workload","terminal_pending_residence"):
                        key=(name,json.dumps(cert,sort_keys=True))
                        if key not in certs:
                            problem,_=case.prepare()
                            assert conflict_check(problem,cert)
                            certs.add(key)
                width_h=delta(h["upper"],h["lower"])
                width_m=delta(m["upper"],m["lower"])
                events=[e for e in m["raw"]["trace"] if e.get("tool")=="learned_query"]
                changes=sum(e["tick"]!=e["default_tick"] for e in events)
                for e in events:
                    decisions[e["chosen"]]+=1
                    policies["changed" if e["tick"]!=e["default_tick"] else "same"]+=1
                    inference.append(e["seconds"])
                rows.append(dict(case=name,budget=b,repeat=rep,human=endpoint(h),learned=endpoint(m),
                         human_status=h["status"], learned_status=m["status"],result=classify(h,m),
                         human_lower=h["lower"],human_upper=h["upper"],learned_lower=m["lower"],learned_upper=m["upper"],
                         lower_gain=delta(m["lower"],h["lower"]),upper_gain=delta(h["upper"],m["upper"]),
                         gap_reduction=delta(width_h,width_m),human_seconds=h["wall"],learned_seconds=m["wall"],
                         human_late=h["late"],learned_late=m["late"],decisions=len(events),overrides=changes,
                         human_reason=why(h),learned_reason=why(m)))
        lows=[r["lower"] for r in all_records if r["lower"] is not None]
        caps=[r["upper"] for r in all_records if r["upper"] is not None]
        assert not lows or not caps or max(lows)<=min(caps)
        assert not lows or all(r["status"]!="INFEASIBLE_AT_ZERO" for r in all_records)
    with (root/"paired.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    summary=[]
    for b in (1,30):
        for rep in (0,1):
            batch=[r for r in rows if (r["budget"],r["repeat"])==(b,rep)]
            summary.append(dict(budget=b,repeat=rep,human_proofs=sum(r["human_status"]!="UNKNOWN" for r in batch),
                learned_proofs=sum(r["learned_status"]!="UNKNOWN" for r in batch),classes=dict(Counter(r["result"] for r in batch)),
                human_late=sum(r["human_late"] for r in batch),learned_late=sum(r["learned_late"] for r in batch),
                changed_cases=[r["case"] for r in batch if r["overrides"]],gain=[r["case"] for r in batch if r["result"]=="新增证明"],
                loss=[r["case"] for r in batch if r["result"]=="丢失证明"]))
    save(root/"audit.json",dict(runs=len(rows)*2,witness_occurrences=occurrences,distinct_replayed=len(witnesses),
         arithmetic_certificates=len(certs),goals=dict(decisions),comparisons=dict(policies),
         median_inference_ms=1000*median(inference) if inference else None,summary=summary))
    md=["# 新快照逐例对照","", "时间单位为秒。两端均有证据才计算区间宽度；? 表示没有已验证的下界，不能用 0 填补。正的差值表示学习策略改善。人和学分别为原人工策略和学习策略。"]
    for rep in (0,1):
        for b in (1,30):
            md.extend(["",f"## {b} 秒 · "+("首轮" if rep==0 else "反序复测"),"",
                "|快照|人工策略|学习策略|下界提高|上界降低|区间缩小|判定|学习策略末次回执或状态|",
                "|---|---|---|---:|---:|---:|---|---|"])
            for r in rows:
                if (r["budget"],r["repeat"])==(b,rep):
                    cells=[r[k] for k in ("case","human","learned","lower_gain","upper_gain","gap_reduction","result","learned_reason")]
                    md.append("|"+"|".join(str(x) if x is not None else "—" for x in cells)+"|")
    (root/"cases.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=True))
    

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=DEFAULT)
    review(ap.parse_args().root)
