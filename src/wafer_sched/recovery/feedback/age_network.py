"""Necessary joint robot/chamber flow for immediate repair on uniform terminal suffixes."""
from collections import defaultdict
from math import ceil



def matrix(domain, quantum, *, repair=0, failed=None, final=None, singleton=False):
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
    if repair<0 or (repair and failed not in cs):
        raise ValueError("Invalid repair gate")
    gate=max(0,(repair-P-d)//quantum)
    m=len(cs)
    if m>3:
        raise ValueError("Flow domain limited to three terminal chambers")
    if final is not None:
        rank, job = final
        if not (0 <= job < len(jobs) and 0 <= 2*(len(jobs)-1)-rank < m):
            raise ValueError("Invalid last-inbound partition")
    prefix_moves=[]
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
    # A chamber available to exactly one wafer can be entered at most once.
    # Track that fact along each individual flow path, including the final load.
    scarce = {c for c in range(m) if sum(cs[c] in dict(j.choices) for j in jobs)==1} if singleton else set()
    start=(0,empty,0,0)
    finish=(endmode,empty,gate,0)
    states=[start]
    index={start:0}
    incoming=defaultdict(list)
    outgoing=defaultdict(list)
    unload=defaultdict(list)
    cost=[]
    arcs=[]
    bounds=[]
    table=[]
    def advance(ages,delta):
        return tuple(a+delta if a>=0 else -1 for a in ages)
    def put(mode,ages,c,val):
        return mode,ages[:c]+(val,)+ages[c+1:]
    clock_cap=max(j.due for j in jobs)//quantum+1+len(jobs)*(max(maximum)+step+2)
    def edge(target,price=0,tag=None,elapsed=0,move=False):
        mode,ages=target
        bucket=min(gate,source[2]+elapsed)
        # Once all wafers leave, the absolute clock has no further constraints.
        spent=source[3]
        for c in scarce:
            if source[1][c]<0 and ages[c]>=0:
                if spent & (1<<c):
                    return
                spent |= 1<<c
        target=finish if mode==endmode and ages==empty else (mode,ages,bucket,spent)
        if any(a>b for a,b in zip(ages,maximum)) or target==source:
            return
        if target not in index:
            index[target]=len(states)
            states.append(target)
        dest=index[target]
        # Idle edges can recur up to the total time horizon, use a conservative cap.
        cap=clock_cap if tag is None else len(jobs)
        x=len(bounds)
        bounds.append((0,cap))
        arcs.append(x)
        incoming[dest].append(x)
        outgoing[idx].append(x)
        if final is not None and move and source[0]==0:
            prefix_moves.append((x,1))
        if price:
            cost.append((x,price))
        if tag:
            unload[tag].append(x)
    for idx,source in enumerate(states):
        mode,ages,bucket,_=source
        if source==finish: continue
        edge((mode,advance(ages,1)),quantum if mode==0 else 0,elapsed=1)
        later=advance(ages,step)
        for c,age in enumerate(ages):
            if mode==0 and age<0:
                if cs[c]!=failed or bucket==gate:
                    edge(put(0,later,c,step),S,elapsed=step,move=True)
                if final is None or (cs[c] in dict(jobs[job].choices) and
                        sum(a>=0 for a in ages)==2*(len(jobs)-1)-rank):
                    edge((1+c,ages),P)
            elif mode==1+c and (cs[c]!=failed or bucket==gate):
                edge(put(1+m+c,later,c,step),elapsed=step)
            if 1<=mode<=m or age<0 or not elig.get((c,age)):
                continue
            last=(mode==1+m+c)
            edge(put(endmode if last else mode,later,c,-1),S if mode==0 else 0,(c,age,last),elapsed=step,move=True)
    if finish not in index:
        raise ValueError("Empty age-flow graph")
    for k,state in enumerate(states):
        rhs=int(state==start)-int(state==finish)
        table.append(([(x,1) for x in outgoing[k]]+[(x,-1) for x in incoming[k]],rhs,rhs))
    assignments=defaultdict(list)
    last_dues=[]
    for (c,age,last),group in unload.items():
        selected=[]
        for i in elig[c,age]:
            if final is not None and (i==job)!=last:
                continue
            y=len(bounds)
            bounds.append((0,1))
            selected.append(y)
            assignments[i].append(y)
            if last: last_dues.append((y,-jobs[i].due))
        table.append(([(x,1) for x in group]+[(y,-1) for y in selected],0,0))
    for i in range(len(jobs)):
        table.append(([(y,1) for y in assignments[i]],1,1))
    if final is not None:
        table.append((prefix_moves,rank,rank))
    table.append((cost+last_dues,-(1<<63),0))
    return bounds,table,dict(states=len(states),arcs=len(arcs),quantum=quantum)

