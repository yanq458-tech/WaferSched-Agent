"""Constructive terminal search. Reordering failures never exclude a repair time."""

from collections import deque
from random import Random
from time import perf_counter


def unpack(domain, schedule):
    jobs = domain[0]
    by_wafer = {j.wafer: i for i, j in enumerate(jobs)}
    choices = [None] * len(jobs)
    sequence = []
    for row in sorted(schedule["transfers"], key=lambda t: t["pick_start"]):
        i = by_wafer[row["wafer_id"]]
        outgoing = row["destination"] == "OUT"
        if not outgoing:
            choices[i] = row["destination"]
        sequence.append(2*i + outgoing)
    return sequence, choices


def timing(p, domain, seq, chambers, repair, *, soft=False):
    """Earliest feasible retiming of a fixed order. Soft mode scores missed source dues."""
    jobs, P, L, d = domain
    n = len(jobs)
    edges = [[] for _ in range(3*n)]
    dist = [0]*(3*n)
    occupied = set()
    prev = None
    lag = 0
    for move in seq:
        i, out = divmod(move,2)
        j, c = jobs[i], chambers[i]
        a,b,u = 3*i,3*i+1,3*i+2
        dest = u if out else a
        if prev is not None:
            edges[prev].append((dest,lag))
        if out:
            if c not in occupied:
                return None
            occupied.remove(c)
            prev, lag = u,P+L+2*d
        else:
            if c in occupied:
                return None
            occupied.add(c)
            t = dict(j.choices).get(c)
            if t is None or (j.hold_out is not None and j.hold_out < d+L):
                return None
            dist[a] = max(0,j.ready,d if p.snapshot["robot"]["position"]!=j.source else 0)
            dist[b] = repair if c == p.failed_chamber else 0
            edges[a].append((b,P+d))
            edges[b].append((u,L+t))
            if j.hold_in is not None:
                edges[b].append((a,L-P-j.hold_in))
            if j.residence is not None:
                edges[u].append((b,P-L-t-j.residence))
            prev, lag = b,L+d
    # Bellman-Ford queue; a strictly improving path of V edges contains a positive cycle.
    count = len(dist)
    queue = deque(range(count))
    inside = [True]*count
    depth = [0]*count
    while queue:
        i = queue.popleft()
        inside[i] = False
        for k,w in edges[i]:
            val = dist[i]+w
            if val > dist[k]:
                dist[k] = val
                depth[k] = depth[i]+1
                if depth[k] >= count:
                    return None
                if not inside[k]:
                    queue.append(k)
                    inside[k] = True
    penalty = sum(max(0,dist[3*i]+P-j.due) for i,j in enumerate(jobs) if j.due is not None)
    return (penalty,dist) if soft or penalty == 0 else None


def schedule(domain, scale, seq, chambers, dist):
    jobs,P,L,d = domain
    moves, procs = [], []
    for m in seq:
        i,out = divmod(m,2)
        j,c = jobs[i],chambers[i]
        a,b,u = dist[3*i:3*i+3]
        if out:
            a,b = u,u+P+d
        else:
            procs.append(dict(wafer_id=j.wafer,stage=j.stage,chamber=c,start=b+L,end=b+L+dict(j.choices)[c]))
        moves.append(dict(wafer_id=j.wafer,stage=j.stage+out,source=c if out else j.source,
                          destination="OUT" if out else c,pick_start=a,pick_end=a+P,
                          place_start=b,place_end=b+L,initially_carried=False))
    return dict(transfers=moves,processes=procs,ticks_per_second=scale,makespan_tick=moves[-1]["place_end"])


def lift(p, domain, seq, chambers, lower, cap):
    # Feasible only on this fixed order; the resulting upper is never used globally.
    data = timing(p,domain,seq,chambers,lower)
    if data is None:
        return None
    upper = cap
    while lower < upper:
        mid = (lower+upper+1)//2
        test = timing(p,domain,seq,chambers,mid)
        if test is None:
            upper=mid-1
        else:
            lower,data=mid,test
    return lower,schedule(domain,p.scale,seq,chambers,data[1])


def greedy(p, domain, repair, rng):
    jobs,P,L,d = domain
    n=len(jobs)
    remaining=set(range(n))
    pos=p.snapshot["robot"]["position"]
    busy={}
    seq=[]
    chambers=[None]*n
    clock=0
    counts={c:sum(1/len(j.choices) for j in jobs if c in dict(j.choices)) for j in jobs for c,_ in j.choices}
    while remaining or busy:
        opts=[]
        for c,(i,ready,expiry) in busy.items():
            a=max(clock,ready)
            score=a+max(0,expiry-a)*0.16+rng.uniform(-14,14)
            opts.append((score,2*i+1,c,a+P+2*d+L,0,0))
        for i in remaining:
            j=jobs[i]
            a=max(clock,j.ready,0 if seq or pos==j.source else d)
            for c,t in j.choices:
                if c in busy:
                    continue
                b=max(a+P+d, repair if c==p.failed_chamber else 0)
                end=b+L+d
                # Prefer a chamber that can work while other transfers execute.
                risk=sum(max(0,end+P-exp) for _,_,exp in busy.values())
                score=a+0.30*t+0.13*(j.due-P-a)+3*(len(j.choices)-1)+0.7*counts[c]+2*risk+rng.uniform(-22,22)
                opts.append((score,2*i,c,end,b+L+t,b+L+t+j.residence))
        if not opts:
            return None
        _,m,c,clock,ready,expiry=min(opts)
        i,out=divmod(m,2)
        if out:
            del busy[c]
        else:
            remaining.remove(i)
            chambers[i]=c
            busy[c]=(i,ready,expiry)
        seq.append(m)
    return seq,chambers


def mutate(seq, chambers, jobs, rng):
    """Move a wafer's load/unload into a free chamber gap, or exchange eligible identities."""
    n=len(jobs)
    i=rng.randrange(n)
    if rng.random()<0.22:
        j=rng.randrange(n)
        if i==j or chambers[i] not in dict(jobs[j].choices) or chambers[j] not in dict(jobs[i].choices):
            return None
        new=chambers.copy()
        new[i],new[j]=new[j],new[i]
        return [2*(j if k//2==i else i if k//2==j else k//2)+k%2 for k in seq],new
    c=rng.choice(jobs[i].choices)[0]
    other=[k for k in seq if k//2!=i]
    gaps=[]
    first=0
    for k,m in enumerate(other):
        if chambers[m//2]==c:
            if m%2:
                first=k+1
            else:
                gaps.append((first,k))
    gaps.append((first,len(other)))
    left,right=rng.choice(gaps)
    a=rng.randint(left,right)
    b=rng.randint(a,right)
    new=chambers.copy()
    new[i]=c
    return other[:a]+[2*i]+other[a:b]+[2*i+1]+other[b:],new


def improve(p,domain,cap,deadline,incumbent=None):
    jobs=domain[0]
    rng=Random(7103)
    best=incumbent
    origin=unpack(domain,best[1]) if best else None
    target=best[0]+1 if best else 0
    attempts=0
    best_soft=None
    while target<=cap and perf_counter()<deadline:
        if origin and rng.random()<0.8:
            current=origin
        elif best_soft and rng.random()<0.65:
            current=best_soft[1]
        else:
            current=greedy(p,domain,target,rng)
        data=timing(p,domain,*current,target,soft=True)
        score=data[0] if data else float("inf")
        for step in range(100):
            if perf_counter()>=deadline:
                break
            if score==0:
                best=lift(p,domain,*current,target,cap)
                origin=current
                target=best[0]+1
                best_soft=None
                break
            if best_soft is None or score<best_soft[0]:
                best_soft=(score,current)
            proposal=mutate(*current,jobs,rng)
            if proposal is None:
                continue
            attempts+=1
            d=timing(p,domain,*proposal,target,soft=True)
            if d is None:
                continue
            trial=d[0]
            if trial<=score or (trial-score < 20 and rng.random()<0.12):
                score,current=trial,proposal
    return best,attempts
