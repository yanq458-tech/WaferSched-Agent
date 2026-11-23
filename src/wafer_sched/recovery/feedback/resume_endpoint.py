"""Resume an archived, exhaustive last-inbound partition on the same terminal snapshot."""
import argparse
import gzip
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from ortools.sat.python import cp_model

from . import slot_query
from .last_job_probe import submodel
from .frontier_witness import lift
from .target_queries import Continuation, digest, load, record_plan, save, terminal_domain


def freeze(src, parent, children):
    """Check snapshot, exhaustive coverage and exact archived models without solving."""
    case = Continuation.from_dict(load(src))
    p, h = case.prepare()
    domain = terminal_domain(p)
    base, split = load(parent/"result.json"), load(children/"result.json")
    q = split["tick"]
    assert q == base["tick"] and digest(src) == split["snapshot"] == base["snapshot"]
    ranks = list(slot_query.ranks(domain))
    assert sorted(row["last"] for row in base["partitions"]) == ranks
    remaining = []
    retained = []
    def check(folder, filename, expected, model):
        raw = gzip.decompress((folder/filename).read_bytes())
        assert sha256(raw).hexdigest() == expected
        assert model.proto.SerializeToString(deterministic=True) == raw
    for row in base["partitions"]:
        k = row["last"]
        check(parent, f"last-{k}.pb.gz", base["model_sha256"][str(k)], slot_query.build(p,domain,q,k)[0])
        if row["status"] == "INFEASIBLE":
            retained.append([k,None])
            continue
        rows = [t for t in split["subpartitions"] if t["rank"] == k]
        assert sorted(t["index"] for t in rows) == list(range(len(domain[0])))
        for t in rows:
            i = t["index"]
            assert t["wafer"] == domain[0][i].wafer
            check(children,f"rank-{k}-job-{i}.pb.gz",t["model_sha256"],submodel(p,domain,q,k,i)[0])
            assert t["status"] in ("UNKNOWN","INFEASIBLE")
            (retained if t["status"] == "INFEASIBLE" else remaining).append([k,i])
    return dict(snapshot=digest(src),floor_tick=q,remaining=remaining,excluded=retained,
                parent=str(parent/"result.json"),parent_sha256=digest(parent/"result.json"),
                children=str(children/"result.json"),children_sha256=digest(children/"result.json"))


def restricted(p,domain,q,k,i):
    model, opts, idle, held = slot_query.build(p,domain,q,k,last_job=i)
    slot_query.add_gap_cuts(model,domain,k,opts,idle,held)
    jobs,P,L,d = domain
    period = P+L+2*d
    # Each rank's baseline is one whole transfer. Intervals [u,v+1)
    # on the same chamber are disjoint. The processing wait is additional
    # and lies strictly between its inbound placement and outbound pickup.
    # Stop charging at the start of k, before any final inbound holding.
    terms = defaultdict(list)
    for j,c,u,v,x in opts:
        if u >= k:
            continue
        slots = min(k,v+1)-u
        wait = max(0,P+d+L+dict(jobs[j].choices)[c]-(v-u)*period) if v<k else 0
        terms[c].append((slots*period+wait)*x)
    for c, work in terms.items():
        earliest = max(0,q-P-d) if c==p.failed_chamber else 0
        # Earliest is the virtual transfer start, i.e. after inbound holding.
        # If the inventory in this chamber is empty, work is zero.
        if earliest <= k*period:
            model.add(sum(work) <= k*period+idle[k]-earliest)
        else:
            used = model.new_bool_var("used_before_last")
            model.add(sum(work)==0).only_enforce_if(used.Not())
            model.add(sum(work)<=k*period+idle[k]-earliest).only_enforce_if(used)
    return model,opts


def leaf(p,domain,q,k,i,end,*,workers=1,export=None,compact=True):
    start = perf_counter()
    model,opts = (restricted if compact else submodel)(p,domain,q,k,i)
    row = dict(rank=k,index=i,wafer=domain[0][i].wafer,tick=q)
    if export is not None:
        raw=model.proto.SerializeToString(deterministic=True)
        row["model_sha256"]=sha256(raw).hexdigest()
        name=f"q{q}-k{k}-i{i}.pb.gz"
        (export/name).write_bytes(gzip.compress(raw,compresslevel=1))
        row["file"]=name
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=workers
    solver.parameters.random_seed=11
    solver.parameters.max_time_in_seconds=max(0,end-perf_counter())
    row["build_seconds"]=perf_counter()-start
    status=solver.solve(model)
    if status==cp_model.MODEL_INVALID:
        raise ValueError(model.validate())
    row.update(status=solver.status_name(status),solver_seconds=solver.wall_time,branches=solver.num_branches,
               conflicts=solver.num_conflicts,workers=workers)
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        return row,None
    n=len(domain[0])
    seq,cs=[None]*(2*n),[None]*n
    for j,c,u,v,x in opts:
        if solver.boolean_value(x):
            seq[u],seq[v],cs[j]=2*j,2*j+1,c
    hit=lift(p,domain,seq,cs,q,q)
    assert hit is not None
    return row,hit[1]


def age_proof(p,domain,q,k,i,quantum,end,*,existing=None):
    from . import age_network, flow_price
    bounds,table,size=age_network.matrix(domain,quantum,repair=q,failed=p.failed_chamber,
                                         final=(k,i),singleton=True)
    if existing is None:
        proof=flow_price.solve_table(bounds,table,end)
    else:
        proof=existing
    if proof["status"]=="INFEASIBLE":
        value=flow_price.rational_lower(bounds,table,proof["prices"],proof["denominator"])
        if value!=proof["numerator"] or value<=0:
            raise ValueError("Invalid integer separation certificate")
    return dict(proof,size=size,quantum=quantum,rank=k,index=i,tick=q)


def query(p,domain,q,scope,end,*,compact=True):
    if q<scope["floor_tick"]:
        raise ValueError("Earlier repair cannot reuse these exclusions")
    todo=scope["remaining"]
    trace=[]
    for pos,(k,i) in enumerate(todo):
        now=perf_counter()
        if now>=end:
            break
        until=now+(end-now)/(len(todo)-pos)
        if compact and until-now>=1.8:
            period=domain[1]+domain[2]+2*domain[3]
            quantum=next(v for v in range(max(1,period//3),0,-1) if period%v==0)
            proof=age_proof(p,domain,q,k,i,quantum,now+0.5*(until-now))
            if proof["status"]=="INFEASIBLE":
                trace.append(dict(proof,method="age_flow",wafer=domain[0][i].wafer))
                continue
        row,plan=leaf(p,domain,q,k,i,until,compact=compact)
        trace.append(row)
        if plan:
            return "FEASIBLE",plan,trace
    excluded=len(trace)==len(todo) and all(t["status"]=="INFEASIBLE" for t in trace)
    return "INFEASIBLE" if excluded else "UNKNOWN",None,trace


def investigate(src,scope,previous,out,upper,seconds,workers):
    out.mkdir(parents=True,exist_ok=False)
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    domain=terminal_domain(p)
    assert scope["snapshot"]==digest(src) and h["offset"]==0
    ledger=load(previous/"ledger.json")
    assert ledger["snapshot"]==digest(src) and upper==round(ledger["upper"]*p.scale)
    retained=out/"retained"
    retained.mkdir()
    lower=record_plan(case,p,h,round(ledger["lower"]*p.scale),load(previous/"schedule.json"),retained)
    assert lower==ledger["lower"]
    remaining=scope["remaining"]
    hi=upper
    queries=[]
    for q in dict.fromkeys((scope["floor_tick"],upper)):
        if q>hi or q<=round(lower*p.scale):
            continue
        opened=remaining.copy()
        rows=[]
        for k,i in opened:
            row,plan=leaf(p,domain,q,k,i,perf_counter()+seconds,workers=workers,export=out)
            rows.append(row)
            save(out/f"q{q}-k{k}-i{i}.json",row)
            print(q,row["wafer"],row["status"],round(row["solver_seconds"],2),flush=True)
            if row["status"]=="INFEASIBLE":
                remaining=[e for e in remaining if e!=[k,i]]
            if plan:
                lower=max(lower,record_plan(case,p,h,q,plan,out/f"witness-{q}"))
                break
        st="FEASIBLE" if lower*p.scale>=q else "INFEASIBLE" if not remaining else "UNKNOWN"
        queries.append(dict(tick=q,status=st,opened=opened,rows=rows,remaining=remaining.copy()))
        if st=="INFEASIBLE":
            hi=min(hi,q-1)
    result=dict(snapshot=digest(src),scale=p.scale,lower=lower,upper=hi/p.scale,scope=scope,
                previous_ledger=str(previous/"ledger.json"),queries=queries,per_leaf_seconds=seconds)
    save(out/"result.json",result)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("src","parent","children","previous","out"):
        ap.add_argument("--"+key,type=Path,required=True)
    ap.add_argument("--upper",type=int,required=True)
    ap.add_argument("--seconds",type=float,default=60)
    ap.add_argument("--workers",type=int,default=6)
    a=ap.parse_args()
    scope=freeze(a.src,a.parent,a.children)
    res=investigate(a.src,scope,a.previous,a.out,a.upper,a.seconds,a.workers)
    print(res["lower"],res["upper"])

