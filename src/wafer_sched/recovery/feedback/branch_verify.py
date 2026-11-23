"""Rebuild both fixed queries from frozen snapshots; verify a dual and rerun rank partitions."""
import argparse
import gzip
from hashlib import sha256
from pathlib import Path
from ortools.sat.python import cp_model
from . import age_flow,flow_price,slot_query
from .branch_probe import restrict,validated_scope
from .target_queries import Continuation,terminal_domain,load,save,digest

def verify(inputs,artifacts,prior_route,seconds):
    case_name,scope=validated_scope(inputs.parent,prior_route)
    flow=artifacts/"flow6"
    flow_record=load(flow/"result.json")
    src=inputs/(case_name+".json")
    assert flow_record["snapshot"]==digest(src) and flow_record["tick"]==0
    assert (flow_record["wafer"],flow_record["chamber"])==(scope["wafer"],scope["chamber"])
    p,h=Continuation.from_dict(load(src)).prepare()
    assert h["offset"]==0
    model,_=age_flow.build(restrict(terminal_domain(p),scope["wafer"],scope["chamber"]),flow_record["quantum"])
    raw=gzip.decompress((flow/"age-flow.pb.gz").read_bytes())
    assert model.proto.SerializeToString(deterministic=True)==raw
    assert sha256(raw).hexdigest()==flow_record["hashes"]["age-flow"]
    cert_path=flow/"rational-check.json"
    if not cert_path.exists():
        from time import perf_counter
        new=flow_price.price(model,perf_counter()+seconds)
        if new["status"]!="INFEASIBLE":
            raise RuntimeError("No positive rational dual bound obtained")
        save(cert_path,new)
    cert=load(cert_path)
    num=flow_price.exact_lower(model.proto,cert["prices"],cert["denominator"])
    assert num==cert["numerator"] and num>0
    report=dict(immediate_case=case_name,scope=scope,flow_model_sha256=sha256(raw).hexdigest(),
                numerator=num,denominator=cert["denominator"],ticks_per_second=p.scale,
                branch_status="INFEASIBLE",immediate_status="INFEASIBLE_AT_ZERO")
    f=artifacts/"slot"/"blind-16-h-f1"
    row=load(f/"result.json")
    src=inputs/(row["case"]+".json")
    assert row["snapshot"]==digest(src)
    p,h=Continuation.from_dict(load(src)).prepare()
    dom=terminal_domain(p)
    assert h["offset"]==0 and row["tick"]/p.scale==17.875
    assert [a["last"] for a in row["partitions"]]==list(slot_query.ranks(dom))
    receipts=[]
    for part in row["partitions"]:
        k=part["last"]
        raw=gzip.decompress((f/f"last-{k}.pb.gz").read_bytes())
        assert sha256(raw).hexdigest()==row["model_sha256"][str(k)]
        assert slot_query.build(p,dom,row["tick"],k)[0].proto.SerializeToString(deterministic=True)==raw
        model=cp_model.CpModel()
        model.proto.ParseFromString(raw)
        solver=cp_model.CpSolver()
        solver.parameters.random_seed=29
        solver.parameters.num_search_workers=3
        solver.parameters.max_time_in_seconds=seconds
        st=solver.solve(model)
        assert part["status"]=="INFEASIBLE" and st in (cp_model.INFEASIBLE,cp_model.UNKNOWN)
        receipts.append(dict(last=k,status=solver.status_name(st),seconds=solver.wall_time))
    report["rank_recheck"]=receipts
    report["rank_snapshot"]=row["snapshot"]
    report["rank_query_tick"]=row["tick"]
    report["rank_scale"]=p.scale
    save(artifacts/"verified.json",report)
    return report

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("inputs","artifacts","prior-route"): ap.add_argument("--"+k,required=True,type=Path)
    ap.add_argument("--seconds",type=float,default=75)
    a=ap.parse_args()
    print(verify(a.inputs,a.artifacts,a.prior_route,a.seconds))

