"""Fixed repair on the uniform-travel terminal domain, partitioned by last inbound rank."""

from collections import defaultdict
from time import perf_counter

from ortools.sat.python import cp_model

from .frontier_witness import schedule


def ranks(domain):
    jobs, *_ = domain
    n = len(jobs)
    chambers = {c for j in jobs for c, _ in j.choices}
    # The last inbound must have an empty destination. Other pending wafers occupy
    # distinct chambers. There are 2(n-1)-pending moves before this inbound.
    return range(2*(n-1)-min(n-1,len(chambers)-1), 2*n-1)


def build(p, domain, repair, last, *, last_job=None):
    jobs, pick, place, travel = domain
    size = 2*len(jobs)
    period = pick+place+2*travel
    model = cp_model.CpModel()
    if last not in ranks(domain) or any(None in (j.due,j.residence,j.hold_in) for j in jobs):
        raise ValueError("Unsupported terminal rank or unbounded job windows")
    last_due = max(j.due for j in jobs) if last_job is None else jobs[last_job].due
    # All inbound placements finish by due+holding; all outbound pickups finish by
    # their placement end + processing + residence. Output can be placed immediately.
    horizon = max(j.due+j.hold_in+max(t for _,t in j.choices)+j.residence+period for j in jobs)
    idle = [model.new_int_var(0,horizon,"pick_slack") for k in range(size)]
    held = [model.new_int_var(0,horizon,"place_slack") for k in range(size)]
    for k in range(size):
        model.add(idle[k]<=held[k])
        if k+1<size:
            model.add(held[k]<=idle[k+1])
    model.add(last*period+idle[last]+pick<=last_due)
    slot = [[] for _ in range(size)]
    occupy = defaultdict(list)
    mates = defaultdict(list)
    incoming = defaultdict(list)
    options=[]
    first = min(max(0,j.ready,travel if p.snapshot["robot"]["position"]!=j.source else 0) for j in jobs)
    model.add(idle[0]>=first)
    slack = last_due-pick-last*period
    for i,j in enumerate(jobs):
        rows=[]
        ready=max(j.ready,travel if p.snapshot["robot"]["position"]!=j.source else 0)
        for c,t in j.choices:
            if j.hold_out is not None and j.hold_out<travel+place:
                continue
            for u in range(last+1):
                if last_job is not None and (i == last_job) != (u == last):
                    continue
                if u*period+first+pick>j.due:
                    continue
                if c==p.failed_chamber and u<last and repair>u*period+pick+travel+slack:
                    continue
                max_gap=(travel+place+t+j.residence)//period
                for v in range(u+1,min(size,u+max_gap+1)):
                    if v==last or (v<last and max(0,pick+travel+place+t-(v-u)*period)>slack-first):
                        continue
                    x=model.new_bool_var("")
                    rows.append(x)
                    options.append((i,c,u,v,x))
                    slot[u].append(x)
                    slot[v].append(x)
                    mates[u,v].append(x)
                    incoming[u].append((x,t,j.residence,ready,j.due,j.hold_in,c==p.failed_chamber))
                    for k in range(u,v+1):
                        occupy[c,k].append(x)
        model.add_exactly_one(rows)
    for row in slot:
        model.add_exactly_one(row)
    for row in occupy.values():
        model.add_at_most_one(row)
    for u,rows in incoming.items():
        active=model.new_bool_var("")
        model.add(sum(x for x,*_ in rows)==active)
        a=u*period+idle[u]
        b=u*period+pick+travel+held[u]
        model.add(a>=sum(x*ready for x,_,_,ready,*_ in rows))
        model.add(a+pick<=sum(x*v[3] for x,*v in rows)).only_enforce_if(active)
        model.add(b+place<=a+pick+sum(x*v[4] for x,*v in rows)).only_enforce_if(active)
        model.add(b>=repair*sum(x for x,*v in rows if v[5]))
        # Aggregating duration once per inbound rank avoids one timing constraint per column.
        d=model.new_int_var(0,horizon,"duration")
        window=model.new_int_var(0,horizon,"window")
        model.add(d==sum(x*t for x,t,*_ in rows))
        model.add(window==sum(x*(t+res) for x,t,res,*_ in rows))
        for v in range(u+1,size):
            group=mates.get((u,v))
            if not group:
                continue
            linked=model.new_bool_var("")
            model.add(sum(group)==linked)
            model.add(v*period+idle[v]>=b+place+d).only_enforce_if(linked)
            model.add(v*period+idle[v]+pick<=b+place+window).only_enforce_if(linked)
    return model, options, idle, held



def add_gap_cuts(model,domain,last,options,idle,held):
    """Charge unavoidable processing waits only to disjoint rank gaps."""
    jobs,P,L,d=domain
    period=P+L+2*d
    pairs=defaultdict(list)
    per_chamber=defaultdict(list)
    singles=[]
    doubles=defaultdict(list)
    for i,c,u,v,x in options:
        g=v-u
        debt=max(0,P+d+L+dict(jobs[i].choices)[c]-g*period)
        if not debt: continue
        term=debt*x
        pairs[u,v].append(term)
        if v>=last: continue
        per_chamber[c].append((u,v,term))
        if g==1: singles.append(term)
        if g==2: doubles[c].append(term)
    for (u,v),terms in pairs.items():
        model.add(sum(terms)<=idle[v]-held[u])
    for terms in doubles.values():
        model.add(sum(singles)+sum(terms)<=idle[last]-idle[0])
    for group in per_chamber.values():
        for k in range(0,last,4):
            model.add(sum(t for u,v,t in group if u>=k)<=idle[last]-idle[k])
            model.add(sum(t for u,v,t in group if v<=k)<=idle[k]-idle[0])

def query(p,domain,repair,deadline,*,workers=1,seed=11,export=None,enhanced=False):
    partitions=list(ranks(domain))
    trace=[]
    for idx,last in enumerate(partitions):
        if perf_counter()>=deadline:
            break
        model,options,idle,held=build(p,domain,repair,last)
        if enhanced:
            add_gap_cuts(model,domain,last,options,idle,held)
        if export:
            export(last,model)
        solver=cp_model.CpSolver()
        solver.parameters.num_search_workers=workers
        solver.parameters.random_seed=seed
        solver.parameters.max_time_in_seconds=max(0,(deadline-perf_counter())/(len(partitions)-idx))
        st=solver.solve(model)
        if st==cp_model.MODEL_INVALID:
            raise ValueError(model.validate())
        trace.append(dict(last=last,status=solver.status_name(st),seconds=solver.wall_time,branches=solver.num_branches))
        if st in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            jobs,P,L,d=domain
            period=P+L+2*d
            seq=[None]*(2*len(jobs))
            chambers=[None]*len(jobs)
            dist=[0]*(3*len(jobs))
            for i,c,u,v,x in options:
                if solver.boolean_value(x):
                    seq[u],seq[v]=2*i,2*i+1
                    chambers[i]=c
                    dist[3*i:3*i+3]=[u*period+solver.value(idle[u]),u*period+P+d+solver.value(held[u]),
                                      v*period+solver.value(idle[v])]
            return "FEASIBLE",schedule(domain,p.scale,seq,chambers,dist),trace
    excluded=len(trace)==len(partitions) and all(e["status"]=="INFEASIBLE" for e in trace)
    return "INFEASIBLE" if excluded else "UNKNOWN",None,trace
