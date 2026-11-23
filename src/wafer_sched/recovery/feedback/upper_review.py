"""Independently replay the continuation ledger, model encodings and certificates."""
import argparse
from collections import Counter
from copy import deepcopy
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from ortools.sat import cp_model_pb2
from ortools.sat.python import cp_model

from . import gate_projection, upper_campaign as campaign
from .boundary_campaign import ARCHIVE, atomic, upper
from .target_queries import Continuation,digest,load,replay_incident,replay_recovery,terminal_domain
from . import age_network,flow_price
from .frontier_witness import unpack,timing


def projection_witness(p,domain,plan,gate):
    """Substitute a real timetable into every row of the necessary model, no solver."""
    jobs,P,L,d=domain
    S=P+L+2*d
    moves=sorted(plan["transfers"],key=lambda x:x["pick_start"])
    K=max(i for i,x in enumerate(moves) if x["destination"]!="OUT")
    H=min([K]+[i for i,x in enumerate(moves) if x["destination"]==p.failed_chamber])
    first=min(max(0,j.ready,0 if p.snapshot["robot"]["position"]==j.source else d) for j in jobs)
    cut=moves[K]["pick_start"] if H==K else moves[H]["place_start"]-P-d
    vals={"repair":gate,"head_moves":H,"body_moves":K-H,"head_idle":cut-first-H*S,
          "body_idle":moves[K]["pick_start"]-cut-(K-H)*S,"failed_used_before_last":int(H<K),
          "last_F":int(moves[K]["destination"]==p.failed_chamber)}
    m,_=gate_projection.build(p,domain,gate,gate)
    proto=m.proto
    x=[vals.get(v.name,0) for v in proto.variables]
    # Enumerate the columns of each wafer and select its actual inclusive overlap counts.
    equations=[c.exactly_one.literals for c in proto.constraints if c.HasField("exactly_one")]
    for j,options in zip(jobs,equations):
        u,v=[i for i,t in enumerate(moves) if t["wafer_id"]==j.wafer]
        aa=max(0,min(H,v+1)-u)
        bb=max(0,min(K,v+1)-max(u,H))
        patterns=[]
        for chamber,t in j.choices:
            if j.hold_out is not None and j.hold_out<L+d: continue
            for g in range(1,min(2*len(jobs)-1,(d+L+t+j.residence)//S)+1):
                for a in range(g+2):
                    for b in range(g+2-a):
                        z=g+1-a-b
                        if (a and chamber==p.failed_chamber) or z==1 or (a and b==1 and z==0): continue
                        patterns.append((chamber,g,a,b))
        assert len(patterns)==len(options)
        x[options[patterns.index((moves[u]["destination"],v-u,aa,bb))]]=1
    def inside(value,domain):
        return any(l<=value<=r for l,r in zip(domain[::2],domain[1::2]))
    def lit(k):
        return x[k] if k>=0 else 1-x[-1-k]
    for v,a in zip(proto.variables,x): assert inside(a,v.domain)
    for row in proto.constraints:
        if not all(lit(k) for k in row.enforcement_literal): continue
        kind=row.WhichOneof("constraint")
        if kind=="linear":
            value=sum(x[i]*w for i,w in zip(row.linear.vars,row.linear.coeffs))
            assert inside(value,row.linear.domain),(value,row)
        elif kind=="exactly_one": assert sum(lit(k) for k in row.exactly_one.literals)==1
        elif kind=="at_most_one": assert sum(lit(k) for k in row.at_most_one.literals)<=1
        elif kind=="bool_or": assert any(lit(k) for k in row.bool_or.literals)
        else: raise ValueError(kind)
    return len(proto.constraints)


def verify_plan(inputs,file,lo):
    case,p,h,domain=inputs
    plan=load(file)
    q=min(t["place_start"] for t in plan["transfers"] if t["destination"]==p.failed_chamber)
    assert q==lo and h["offset"]==0
    replay=replay_recovery(p,q/p.scale,plan)
    assert replay["valid"]
    report=dict(witness_repair_delay_seconds=q/p.scale,makespan_seconds=plan["makespan_tick"]/p.scale)
    replay_incident(case,h,report,dict(verification=replay))
    rows=projection_witness(p,domain,plan,q)
    return dict(file=str(file),sha256=digest(file),replay=str(file.parent/f"replay-{q}.json"),
                repair=q/p.scale,makespan=report["makespan_seconds"],completed=len(report["completed_at"]),
                projected_rows_checked=rows)


def audit(out):
    before=load(out/"before.json")
    state=load(out/"state.json")
    assert digest(out/"before.json")==state["upper_binding"][0]
    assert digest(Path(campaign.__file__))==state["upper_binding"][1]
    assert digest(Path(gate_projection.__file__))==state["upper_binding"][2]
    assert state["binding"]==before["binding"] and state["history"]==before["history"]
    jobs=deepcopy(before["jobs"])
    inputs={}
    finals={}
    for n,j in jobs.items():
        src=ARCHIVE/"inputs"/(n+".json")
        assert digest(src)==before["binding"][n][0]
        case=Continuation.from_dict(load(src))
        p,h=case.prepare()
        inputs[n]=case,p,h,terminal_domain(p)
        finals[n]=verify_plan(inputs[n],Path(j["witness"]),j["lower"])
    proofs=[]
    plans=[]
    actions=state["upper_actions"]
    for i,row in enumerate(actions):
        n=row["case"]
        j=jobs[n]
        case,p,h,domain=inputs[n]
        lo=j["lower"];hi=upper(j)
        assert row["old"]==[lo,hi]
        low,high=row["after"]
        assert lo<=low<=high<=hi
        q=row["q"]
        if high<hi:
            file=Path(row["file"])
            info=dict(action=i,case=n,method=row["tool"],status=row["status"],prior=hi/p.scale,
                      upper=high/p.scale,ruled_out=[(high+1)/p.scale,hi/p.scale],
                      file=str(file),sha256=digest(file),threshold=q)
            if row["tool"]=="flow":
                proof=load(file)
                b,t,_=age_network.matrix(domain,row["quantum"],repair=q,failed=p.failed_chamber,singleton=True)
                val=flow_price.rational_lower(b,t,proof["prices"],proof["denominator"])
                assert val==proof["numerator"]==row["numerator"] and val>0 and high==q-1
                info["numerator"]=val
            else:
                if row["tool"]=="endpoint":
                    model=campaign.compact(p,domain,q,j["parts"],load(Path(j["witness"])),row["seed"],False).model
                else:
                    assert row["tool"] in ("projection_fixed","projection_max")
                    model,v=gate_projection.build(p,domain,q,hi)
                    if row["tool"]=="projection_max": model.maximize(v)
                raw=gzip.decompress(file.read_bytes())
                assert hashlib.sha256(raw).hexdigest()==row["model_sha256"]
                assert raw==model.proto.SerializeToString(deterministic=True)
                response=file.parent/"response.pb"
                pb=cp_model_pb2.CpSolverResponse.FromString(response.read_bytes())
                assert cp_model_pb2.CpSolverStatus.Name(pb.status)==row["status"]
                if row["status"]=="INFEASIBLE": assert high==q-1
                else:
                    assert row["tool"]=="projection_max"
                    bounds=row["bound_events"][:]
                    if row["status"] in ("OPTIMAL","FEASIBLE"):bounds.append(pb.best_objective_bound)
                    assert bounds and high==math.ceil(min(bounds))
                info.update(response=str(response),model_sha256=row["model_sha256"])
            proofs.append(info)
        if low>lo:
            file=Path(row["witness"])
            witness=verify_plan(inputs[n],file,low)
            plans.append(dict(action=i,case=n,**witness));finals[n]=witness
            j.update(lower=low,witness=str(file))
        for part in j["parts"]: part["upper"]=min(part["upper"],high)
        j["parts"]=[b for b in j["parts"] if b["upper"]>low]
        j["turns"]+=1
        assert upper(j)==high
    assert jobs==state["jobs"]
    results=[]
    for n,j in jobs.items():
        old=before["jobs"][n];s=j["scale"]; hi=upper(j)
        local=[a for a in actions if a["case"]==n]
        rank_counts=Counter(x["rank"] for x in j["parts"] if x["upper"]==hi)
        _,p,_,domain=inputs[n]
        seq,cs=unpack(domain,load(Path(j["witness"])))
        fixed_checks=[]
        if hi>j["lower"]:
            for tick in sorted({j["lower"]+1,hi}):
                trial=timing(p,domain,seq,cs,tick,soft=True)
                misses=(None if trial is None else sorted([
                    dict(wafer=w.wafer,late_ticks=trial[1][3*i]+domain[1]-w.due)
                    for i,w in enumerate(domain[0]) if trial[1][3*i]+domain[1]>w.due
                ],key=lambda v:-v["late_ticks"]))
                fixed_checks.append(dict(repair_seconds=tick/s,late_source_picks=misses))
        endpoint=[dict(tick=x["q"],status=x["status"],seconds=x["seconds"],branches=x["branches"],
                       conflicts=x["conflicts"]) for x in local if x["tool"]=="endpoint"]
        results.append(dict(case=n,fixed_witness_order=fixed_checks,global_fixed_queries=endpoint,prior=[old["lower"]/s,upper(old)/s],interval=[j["lower"]/s,hi/s],
            status="FINITE" if hi==j["lower"] else "UNKNOWN",upper_gain=(upper(old)-hi)/s,
            solves=len(local),seconds=sum(a["wall"] for a in local),
            tools=Counter(x["tool"]+"/"+x["status"] for x in local),ranks=rank_counts,final_plan=finals[n],
            current_upper_evidence=next((x["file"] for x in reversed(proofs) if x["case"]==n),j["source"])))
    total=load(out/"summary.json")
    accounting=out/"resume-accounting.json"
    prior_elapsed=0.0
    if accounting.is_file():
        data=json.loads(accounting.read_text(encoding="utf-8-sig"))
        prior_elapsed=sum(r["wall"] for r in actions[:data["checkpoint_actions"]])
        assert abs(prior_elapsed-data["completed_step_seconds"])<0.001
    record=dict(search_seconds=prior_elapsed+total["search_seconds"],last_session_search_seconds=total["search_seconds"],
                completed_action_seconds=sum(r["wall"] for r in actions),prior_actions=len(before["history"]),actions=len(actions),
                upper_evidence=proofs,witnesses=plans,cases=results)
    atomic(out/"audit.json",record)
    with (out/"cases.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["case","prior_L_s","prior_U_s","new_L_s","new_U_s","upper_gain_s","status","steps","wall_s","best_schedule","upper_evidence"])
        for s in results:w.writerow([s["case"],*s["prior"],*s["interval"],s["upper_gain"],s["status"],s["solves"],s["seconds"],s["final_plan"]["file"],s["current_upper_evidence"]])
    def link(file):
        return "<"+Path(os.path.relpath(Path(file).resolve(),out.resolve())).as_posix()+">"
    md=["# 全局上界专项：六例证据索引","","时间均为故障后的秒。每份新见证经原始故障快照重放。CP-SAT 记录包含重建一致的数学模型和原始求解响应；正对偶证书使用整数运算复查。"]
    for s in results:
        n=s["case"]; md+=["",f"## {n}","",f"{s['prior']} → {s['interval']}，{s['status']}。",
            f"当前分支按最后进腔序号计数为 {s['ranks']}。最佳修复时刻的[方案]({link(s['final_plan']['file'])})和[重放]({link(s['final_plan']['replay'])})。"]
        if s["fixed_witness_order"]:
            z=s["fixed_witness_order"][-1]
            misses=z["late_source_picks"]
            if misses:
                details="、".join(f"{v['wafer']} 超出 {v['late_ticks']} 个刻度" for v in misses)
                md+=["",f"固定当前见证的路线与搬运顺序，在 {z['repair_seconds']} 秒重新计算最早可行时刻，源腔取完期限冲突为 {details}。该诊断只针对这一顺序。"]
        for x in proofs:
            if x["case"]==n:
                row=f"- 第 {x['action']} 步，{x['method']}，排除闭区间 {x['ruled_out']}。"
                row+=f"[证据]({link(x['file'])})"
                if "response" in x:row+=f" · [CP-SAT 响应]({link(x['response'])})"
                md+=["",row]
        for x in plans:
            if x["case"]==n:md+=["",f"- 第 {x['action']} 步，允许 {x['repair']} 秒修复，{x['completed']} 片完成。[方案]({link(x['file'])}) · [重放]({link(x['replay'])})。"]
        if not any(x["case"]==n for x in proofs):md+=["",f"本次未进一步收紧，沿用[原上界记录]({link(s['current_upper_evidence'])})。"]
    (out/"evidence.md").write_text("\n".join(md)+"\n",encoding="utf8")
    return record


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path,default=campaign.DEST)
    rec=audit(ap.parse_args().out)
    print("search seconds",rec["search_seconds"],"proofs",len(rec["upper_evidence"]),"new plans",len(rec["witnesses"]))
    print([(r["case"],r["interval"]) for r in rec["cases"]])

