"""Restricted order neighborhoods can produce witnesses only. Failed neighborhoods do not exclude a delay."""
import argparse
import subprocess
from pathlib import Path
from random import Random
from time import perf_counter
from ortools.sat.python import cp_model
from .target_queries import Continuation, terminal_domain, load, save, digest, record_plan
from .order_probe import encode
from .slot_query import build,ranks
from .frontier_witness import lift

def run(src,out,exe,q,upper,seconds):
    out.mkdir(parents=True,exist_ok=False)
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    domain=terminal_domain(p)
    cs,lines=encode(p,domain,q)
    data="\n".join(" ".join(map(str,row)) for row in lines)
    n=len(domain[0])
    rng=Random(49601)
    deadline=perf_counter()+seconds
    trials=[]
    lower=None
    while perf_counter()<deadline-2 and lower is None:
        seed=rng.randrange(1<<30)
        # This executable and its scores only suggest rank neighborhoods.
        child=subprocess.run([str(exe.resolve()),"-","0.9",str(seed)],input=data,text=True,capture_output=True,check=True)
        move,_,log=child.stdout.splitlines()
        seq=list(map(int,move.split()))
        pos={m:k for k,m in enumerate(seq)}
        ordered=sorted(ranks(domain),key=lambda k:abs(k-max(pos[2*i] for i in range(n))))
        for k in ordered:
            if perf_counter()>=deadline or lower is not None: break
            width=rng.choice([2,4,6,8])
            free=set(rng.sample(range(n),max(1,n//4)))
            model,opts,_,_=build(p,domain,q,k)
            blocked=[x for i,c,u,v,x in opts if i not in free and
                     (abs(u-pos[2*i])>width or abs(v-pos[2*i+1])>width)]
            model.add(sum(blocked)==0)
            solver=cp_model.CpSolver()
            solver.parameters.num_search_workers=2
            solver.parameters.max_time_in_seconds=max(0,min(4.0,deadline-perf_counter()))
            status=solver.solve(model)
            trials.append(dict(seed=seed,rank=k,width=width,heuristic_score=float(log.split()[1]),
                               status=solver.status_name(status),branches=solver.num_branches))
            if status in (cp_model.FEASIBLE,cp_model.OPTIMAL):
                candidate=[None]*(2*n)
                chosen=[None]*n
                for i,c,u,v,x in opts:
                    if solver.boolean_value(x):
                        chosen[i]=c
                        candidate[u],candidate[v]=2*i,2*i+1
                witness=lift(p,domain,candidate,chosen,q,upper)
                assert witness
                lower=record_plan(case,p,h,q,witness[1],out)
        save(out/"result.json",dict(case=src.stem,snapshot=digest(src),tick=q,budget=seconds,lower=lower,
                                     status="FEASIBLE" if lower is not None else "UNKNOWN",trials=trials))
    return lower

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("src","out","exe"):
        ap.add_argument("--"+name,type=Path,required=True)
    ap.add_argument("--tick",type=int,default=0)
    ap.add_argument("--upper",type=int,required=True)
    ap.add_argument("--seconds",type=float,default=150)
    a=ap.parse_args()
    print(run(a.src,a.out,a.exe,a.tick,a.upper,a.seconds))

