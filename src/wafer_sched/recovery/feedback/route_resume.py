"""Resolve residual last-job partitions by disjoint terminal-route assignments."""
import argparse
import gzip
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from .resume_endpoint import age_proof, freeze, leaf, restricted
from .target_queries import Continuation, digest, load, record_plan, save, terminal_domain


def choices(domain, assignment):
    jobs=list(domain[0])
    for i,c in assignment:
        duration=dict(jobs[i].choices)[c]
        jobs[i]=replace(jobs[i],choices=((c,duration),))
    return (jobs,*domain[1:])


class Study:
    def __init__(self,src,previous,scope,out):
        self.root=out
        out.mkdir(parents=True,exist_ok=True)
        self.case=Continuation.from_dict(load(src))
        self.p,self.h=self.case.prepare()
        self.dom=terminal_domain(self.p)
        self.scope=scope
        self.previous=previous
        ledger=load(previous/"ledger.json")
        assert ledger["snapshot"]==scope["snapshot"]==digest(src) and self.h["offset"]==0
        self.hi=round(ledger["upper"]*self.p.scale)
        self.lo=round(ledger["lower"]*self.p.scale)
        assert record_plan(self.case,self.p,self.h,self.lo,load(previous/"schedule.json"),out/"retained")==ledger["lower"]
        self.exclusions=[]
        self.visits=[]
        self.witnesses=[]
        self.probes=[]

    def visit(self,q,k,i,assignment,end):
        route=choices(self.dom,assignment)
        key="-".join(f"{j}_{c}" for j,c in assignment) or "any"
        folder=self.root/"tree"/f"q{q}-k{k}-i{i}"/key
        folder.mkdir(parents=True,exist_ok=True)
        def finish(status,evidence,**extra):
            row=dict(tick=q,rank=k,index=i,assignment=assignment,status=status,evidence=evidence,**extra)
            self.visits.append(row)
            if status=="INFEASIBLE":
                self.exclusions.append(row)
            save(folder/"node.json",row)
            print(q,i,key,status,evidence,flush=True)
            return status
        inherited=next((x for x in self.exclusions if x["tick"]<=q and x["rank"]==k and x["index"]==i
                        and set(map(tuple,x["assignment"])).issubset(map(tuple,assignment))),None)
        if inherited:
            return finish("INFEASIBLE","monotone",source=inherited)
        def verify_cp(path,model):
            row=load(path)
            assert (row["tick"],row["rank"],row["index"])==(q,k,i)
            raw=gzip.decompress((path.parent/row["file"]).read_bytes())
            assert sha256(raw).hexdigest()==row["model_sha256"] and model.proto.SerializeToString(deterministic=True)==raw
            return row
        def cp(file,seconds):
            if file.exists():
                return verify_cp(file,restricted(self.p,route,q,k,i)[0])
            row,plan=leaf(self.p,route,q,k,i,perf_counter()+seconds,workers=6,export=file.parent)
            if plan:
                witness=file.parent/"witness"
                gate=record_plan(self.case,self.p,self.h,q,plan,witness)
                self.lo=max(self.lo,round(gate*self.p.scale))
                self.witnesses.append(str(witness/"schedule.json"))
                row["plan"]=str(witness/"schedule.json")
            save(file,row)
            return row
        def verdict(row,path):
            if row["status"]=="INFEASIBLE":
                return finish("INFEASIBLE","cp_sat",file=str(path))
            if row["status"] in ("OPTIMAL","FEASIBLE"):
                file=Path(row["plan"])
                gate=record_plan(self.case,self.p,self.h,q,load(file),file.parent)
                self.lo=max(self.lo,round(gate*self.p.scale))
                if str(file) not in self.witnesses: self.witnesses.append(str(file))
                return finish("FEASIBLE","replay",file=str(file))
        if not assignment and q==self.scope["floor_tick"]:
            file=self.root/f"q{q}-k{k}-i{i}.json"
            st=verdict(cp(file,55),file)
            if st: return st

        # Cached exploratory certificates use the same matrix, checked with integer arithmetic.
        previous_children=any(x["tick"]<q and x["rank"]==k and x["index"]==i and
                              x["assignment"]==assignment and "split" in x for x in self.visits)
        period=route[1]+route[2]+2*route[3]
        for quantum,allow in ((6,3),(3,7),(2,22)):
            if period%quantum or previous_children: continue
            legacy=None
            if not assignment:
                legacy=self.root/f"age{q}-{i}-single-{quantum}.json"
            elif len(assignment)==1 and assignment[0][0]==i:
                legacy=self.root/f"route-{assignment[0][1]}-q{q}-d{quantum}.json"
            path=legacy if legacy and legacy.exists() else folder/f"age-{quantum}.json"
            if path.exists():
                proof=load(path)
                if proof["status"]=="INFEASIBLE":
                    age_proof(self.p,route,q,k,i,quantum,end,existing=proof)
            else:
                # Finer grids are reserved for unsplit partitions, where a single
                # certificate can remove many routes from all later repairs.
                if (quantum==2 and assignment) or perf_counter()+0.6>=end:
                    continue
                proof=age_proof(self.p,route,q,k,i,quantum,min(end,perf_counter()+allow))
                save(path,proof)
            if proof["status"]=="INFEASIBLE":
                return finish("INFEASIBLE","rational_age_bound",quantum=quantum,file=str(path))
        alternatives=[j for j,job in enumerate(route[0]) if len(job.choices)>1]
        if alternatives:
            split=i if i in alternatives else max(alternatives,key=lambda j:max(t for _,t in route[0][j].choices))
            prev_split=next((x for x in self.visits if x["tick"]<q and x["rank"]==k and x["index"]==i and
                             x["assignment"]==assignment and x.get("split")==split),None)
            # Traverse inherited subdivisions even after timeout, to preserve their coverage.
            if len(assignment)<4 and (prev_split or perf_counter()+2<end):
                children=[]
                for pos,(c,_) in enumerate(route[0][split].choices):
                    now=perf_counter()
                    limit=now+max(0,end-now)/(len(route[0][split].choices)-pos)
                    st=self.visit(q,k,i,assignment+[(split,c)],limit)
                    children.append([c,st])
                    if st=="FEASIBLE":
                        return finish(st,"child_witness",split=split,children=children)
                st="INFEASIBLE" if all(v=="INFEASIBLE" for _,v in children) else "UNKNOWN"
                return finish(st,"route_partition",split=split,children=children)
        file=folder/"exact.json"
        if file.exists() or perf_counter()+1.5<end:
            st=verdict(cp(file,max(0,end-perf_counter())),file)
            if st: return st
        return finish("UNKNOWN","budget_or_relaxation",file=str(file) if file.exists() else None)

    def run(self,seconds):
        initial_upper=self.hi
        for q in dict.fromkeys((self.scope["floor_tick"],initial_upper)):
            if q>self.hi or q<=self.lo:
                continue
            rows=[]
            for k,i in self.scope["remaining"]:
                status=self.visit(q,k,i,[],perf_counter()+seconds)
                rows.append(dict(rank=k,index=i,status=status))
                if status=="FEASIBLE": break
            st="FEASIBLE" if self.lo>=q else "INFEASIBLE" if all(r["status"]=="INFEASIBLE" for r in rows) else "UNKNOWN"
            self.probes.append(dict(tick=q,status=st,groups=rows))
            if st=="INFEASIBLE": self.hi=q-1
            assert self.lo<=self.hi
        result=dict(scope=self.scope,queries=self.probes,scale=self.p.scale,lower=self.lo/self.p.scale,
                    upper=self.hi/self.p.scale,rows=self.visits,witnesses=self.witnesses,
                    previous=str(self.previous/"ledger.json"),seconds_per_remaining_job=seconds)
        save(self.root/"result.json",result)
        return result


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("src","parent","children","previous","out"):
        ap.add_argument("--"+key,type=Path,required=True)
    ap.add_argument("--seconds",type=float,default=100)
    a=ap.parse_args()
    scope=freeze(a.src,a.parent,a.children)
    result=Study(a.src,a.previous,scope,a.out).run(a.seconds)
    print(result["lower"],result["upper"])

