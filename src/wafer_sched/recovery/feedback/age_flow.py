"""Necessary joint robot/chamber flow for immediate repair on uniform terminal suffixes."""
from collections import defaultdict
from math import ceil
from ortools.sat.python import cp_model


def build(domain, quantum):
    """Bucket the virtual load starts and output pick starts down on the same grid.

    A chamber's age at pickup must lie between floor((P+d+L+t)/q)
    and ceil((d+L+t+R)/q). This outward rounding only relaxes the window.
    Waiting while carrying an input is moved before its virtual load start;
    the last real pick can precede that virtual start, so its clock stops first.
    """
    jobs,P,L,d=domain
    S=P+L+2*d
    if quantum<1 or S%quantum or any(j.due is None or j.residence is None for j in jobs):
        raise ValueError("Finite terminal windows and a divisor of the move period required")
    cs=sorted({c for j in jobs for c,t in j.choices})
    m=len(cs)
    if m>3:
        raise ValueError("Flow domain limited to three terminal chambers")
    elig=defaultdict(list)
    maximum=[0]*m
    for i,j in enumerate(jobs):
        for c,t in j.choices:
            z=cs.index(c)
            end=ceil((d+L+t+j.residence)/quantum)
            maximum[z]=max(maximum[z],end)
            for a in range((P+d+L+t)//quantum,end+1):
                elig[z,a].append(i)
    step=S//quantum
    empty=(-1,)*m
    # modes: 0 prefix; 1..m hold final input; m+1..2m final wafer in chamber;
    # 2m+1 after its discharge. No new inputs in the last two modes.
    endmode=2*m+1
    start=(0,empty)
    finish=(endmode,empty)
    states=[start]
    index={start:0}
    incoming=defaultdict(list)
    outgoing=defaultdict(list)
    unload=defaultdict(list)
    cost=[]
    arcs=[]
    model=cp_model.CpModel()
    def advance(ages,delta):
        return tuple(a+delta if a>=0 else -1 for a in ages)
    def put(mode,ages,c,val):
        return mode,ages[:c]+(val,)+ages[c+1:]
    clock_cap=max(j.due for j in jobs)//quantum+1+len(jobs)*(max(maximum)+step+2)
    def edge(target,price=0,tag=None):
        mode,ages=target
        if any(a>b for a,b in zip(ages,maximum)) or target==source:
            return
        if target not in index:
            index[target]=len(states)
            states.append(target)
        dest=index[target]
        # Idle edges can recur up to the total time horizon, use a conservative cap.
        cap=clock_cap if tag is None else len(jobs)
        x=model.new_int_var(0,cap,"")
        arcs.append(x)
        incoming[dest].append(x)
        outgoing[idx].append(x)
        if price:
            cost.append(price*x)
        if tag:
            unload[tag].append(x)
    for idx,source in enumerate(states):
        mode,ages=source
        if source==finish: continue
        edge((mode,advance(ages,1)),quantum if mode==0 else 0)
        later=advance(ages,step)
        for c,age in enumerate(ages):
            if mode==0 and age<0:
                edge(put(0,later,c,step),S)
                edge((1+c,ages),P)
            elif mode==1+c:
                edge(put(1+m+c,later,c,step))
            if 1<=mode<=m or age<0 or not elig.get((c,age)):
                continue
            last=(mode==1+m+c)
            edge(put(endmode if last else mode,later,c,-1),S if mode==0 else 0,(c,age,last))
    if finish not in index:
        model.add_bool_or([])
        return model,dict(states=len(states),arcs=len(arcs))
    for k,state in enumerate(states):
        model.add(sum(outgoing[k])-sum(incoming[k])==int(state==start)-int(state==finish))
    assignments=defaultdict(list)
    last_dues=[]
    for (c,age,last),group in unload.items():
        selected=[]
        for i in elig[c,age]:
            y=model.new_bool_var("")
            selected.append(y)
            assignments[i].append(y)
            if last: last_dues.append(jobs[i].due*y)
        model.add(sum(group)==sum(selected))
    for i in range(len(jobs)):
        model.add_exactly_one(assignments[i])
    model.add(sum(cost)<=sum(last_dues))
    return model,dict(states=len(states),arcs=len(arcs),quantum=quantum)

