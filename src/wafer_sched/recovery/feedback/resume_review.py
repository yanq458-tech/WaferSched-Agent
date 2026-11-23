"""Check the exclusion tree, rational bounds, serialized CP models and timed deltas."""
import argparse
import gzip
from collections import Counter
from hashlib import sha256
from pathlib import Path

from .branch_results import compare
from .resume_endpoint import age_proof, freeze, restricted
from .route_resume import choices
from .target_queries import Continuation, digest, load, record_plan, save, terminal_domain
from ..policy_retest import PROVED


def check_tree(src,out):
    result=load(out/"result.json")
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    dom=terminal_domain(p)
    scope=result["scope"]
    parent,split=(Path(scope[key]).parent for key in ("parent","children"))
    assert freeze(src,parent,split)==scope and result["scale"]==p.scale and h["offset"]==0
    evidence={}
    audit=[]
    for node in result["rows"]:
        q,k,i=node["tick"],node["rank"],node["index"]
        a=tuple(map(tuple,node["assignment"]))
        assert [k,i] in scope["remaining"] and q>=scope["floor_tick"]
        key=q,k,i,a
        assert key not in evidence
        domain=choices(dom,a)
        st=node["status"]
        kind=node["evidence"]
        row=dict(tick=q,rank=k,wafer=dom[0][i].wafer,assignment=a,status=st,method=kind)
        if kind=="route_partition":
            j=node["split"]
            assert set(c for c,_ in domain[0][j].choices)==set(c for c,_ in node["children"])
            children=[evidence[q,k,i,a+((j,c),)] for c,_ in node["children"]]
            assert st==("INFEASIBLE" if all(s=="INFEASIBLE" for s in children) else "UNKNOWN")
        elif kind=="rational_age_bound":
            file=Path(node["file"])
            proof=age_proof(p,domain,q,k,i,node["quantum"],0,existing=load(file))
            assert proof["status"]==st=="INFEASIBLE"
            row.update(numerator=proof["numerator"],denominator=proof["denominator"],sha256=digest(file))
        elif kind=="cp_sat":
            file=Path(node["file"])
            rec=load(file)
            assert (rec["tick"],rec["rank"],rec["index"],rec["status"])==(q,k,i,"INFEASIBLE") and st=="INFEASIBLE"
            raw=gzip.decompress((file.parent/rec["file"]).read_bytes())
            assert raw==restricted(p,domain,q,k,i)[0].proto.SerializeToString(deterministic=True)
            assert sha256(raw).hexdigest()==rec["model_sha256"]
            row.update(model_sha256=rec["model_sha256"],receipt_sha256=digest(file))
        elif kind=="monotone":
            older=node["source"]
            old_a=tuple(map(tuple,older["assignment"]))
            assert older["tick"]<=q and set(old_a)<=set(a)
            assert st==evidence[older["tick"],k,i,old_a]=="INFEASIBLE"
        elif kind=="replay":
            plan=load(Path(node["file"]))
            assert record_plan(case,p,h,q,plan,out/"checked-witness")>=q/p.scale and st=="FEASIBLE"
        elif kind=="child_witness":
            assert any(evidence[q,k,i,a+((node["split"],c),)]=="FEASIBLE" for c,_ in node["children"])
            assert st=="FEASIBLE"
        else:
            assert kind=="budget_or_relaxation" and st=="UNKNOWN"
        evidence[key]=st
        audit.append(row)
    prior=load(Path(result["previous"]))
    lo=record_plan(case,p,h,round(prior["lower"]*p.scale),load(out/"retained"/"schedule.json"),out/"retained")
    hi=prior["upper"]
    for rec in result["queries"]:
        q=rec["tick"]
        if rec["status"]=="INFEASIBLE":
            assert all(evidence[q,k,i,()]=="INFEASIBLE" for k,i in scope["remaining"])
            hi=min(hi,(q-1)/p.scale)
    for file in result["witnesses"]:
        plan=load(Path(file))
        gate=min(t["place_start"] for t in plan["transfers"] if t["destination"]==p.failed_chamber)
        lo=max(lo,record_plan(case,p,h,gate,plan,out/"checked-witness"))
    assert (lo,hi)==(result["lower"],result["upper"])
    save(out/"tree-audit.json",dict(snapshot=digest(src),lower=lo,upper=hi,nodes=audit,
                                  counts=Counter(x["method"] for x in audit),root_sha256=digest(out/"result.json")))
    return result


def timed_scope_audit(root,src,result):
    case=Continuation.from_dict(load(src))
    problem,_=case.prepare()
    domain=terminal_domain(problem)
    scope=result["scope"]
    assert load(root/"memory"/src.name)["rank_scope"]==scope
    checks=[]
    for file in root.glob(f"b*/{src.stem}/*.json"):
        run=load(file)
        for event in run["evidence"]["trace"]:
            if event.get("tool")!="resumed_last_inbound": continue
            q=event["repair_tick"]
            assert q>=scope["floor_tick"] and event["prior"]==scope["children_sha256"]
            visited=[]
            for row in event["partitions"]:
                pair=[row["rank"],row["index"]]
                assert pair in scope["remaining"] and pair not in visited and row["tick"]==q
                visited.append(pair)
                if row.get("method")=="age_flow":
                    age_proof(problem,domain,q,*pair,row["quantum"],0,existing=row)
            if event["status"]=="INFEASIBLE":
                assert sorted(visited)==sorted(scope["remaining"])
                assert all(row["status"]=="INFEASIBLE" for row in event["partitions"])
            checks.append(dict(file=str(file),tick=q,branches=len(visited),status=event["status"]))
    save(root/"timed-partition-audit.json",checks)


def analyze(root,previous,out):
    src=root/"inputs"/load(Path(load(out/"result.json")["previous"]))["case"]
    result=check_tree(src.with_suffix(".json"),out)
    timed_scope_audit(root,src.with_suffix(".json"),result)
    old=load(Path(load(previous/"certificates"/"blind-20-h-f3"/"ledger.json")["evidence"]))
    verified={k:old[k] for k in ("immediate_case","immediate_status","rank_snapshot","rank_scale","rank_query_tick","rank_source")}
    assert old["rank_snapshot"]==result["scope"]["snapshot"]
    for row in result["queries"]:
        if row["status"]=="INFEASIBLE" and row["tick"]<=verified["rank_query_tick"]:
            verified.update(rank_query_tick=row["tick"],rank_source=str(out/"result.json"))
    save(out/"verified.json",dict(verified,additional_witnesses=result["witnesses"],audit_sha256=digest(out/"tree-audit.json")))
    compare(root,previous,out)
    from csv import DictReader
    with (root/"paired-deltas.csv").open(encoding="utf-8-sig",newline="") as f:
        deltas=list(DictReader(f))
    report=[]
    for against in ("previous","same_run"):
        for budget,rep in [(1,0),(1,1),(30,0),(30,1)]:
            rows=[r for r in deltas if (r["against"],r["budget"],r["repeat"])==(against,str(budget),str(rep))]
            if not rows: continue
            report.append(dict(against=against,budget=budget,repeat=rep,cases=len(rows),
                   old=sum(r["old_status"] in PROVED for r in rows),new=sum(r["new_status"] in PROVED for r in rows),
                   gained=[r["case"] for r in rows if r["proof_change"]=="1"],
                   lost=[r["case"] for r in rows if r["proof_change"]=="-1"],
                   still_unknown=[r["case"] for r in rows if r["new_status"]=="UNKNOWN"]))
    save(root/"summary.json",report)
    return report


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("root","previous","artifacts"):
        ap.add_argument("--"+key,type=Path,required=True)
    a=ap.parse_args()
    print(analyze(a.root,a.previous,a.artifacts))

