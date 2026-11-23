"""Necessary joint chamber workloads before and after the first failed-chamber load.

The three rank ranges are [0,H), [H,K), [K,2n); K is the last inbound.
Every exact transfer order maps to one column per wafer. A satisfiable
projection alone is not a schedule.
"""
from collections import defaultdict
from ortools.sat.python import cp_model


def build(p,domain,threshold,cap):
    jobs,P,L,d=domain
    n=len(jobs)
    S=P+L+2*d
    model=cp_model.CpModel()
    repair=model.new_int_var(threshold,cap,"repair")
    first=min(max(0,j.ready,0 if p.snapshot["robot"]["position"]==j.source else d) for j in jobs)
    D=max(j.due for j in jobs)-P
    H=model.new_int_var(0,2*n-2,"head_moves")
    B=model.new_int_var(0,2*n-2,"body_moves")
    A=model.new_int_var(0,D,"head_idle")
    V=model.new_int_var(0,D,"body_idle")
    # In a nonempty body the cut is the virtual start of the first F load.
    nonempty=model.new_bool_var("failed_used_before_last")
    model.add(B>=1).only_enforce_if(nonempty)
    model.add(B==0).only_enforce_if(~nonempty)
    model.add(first+H*S+A+P+d>=repair).only_enforce_if(nonempty)
    finish=first+(H+B)*S+A+V
    phases=[[],[]]
    lasts=[]
    failed_lasts=[]
    dues=[]
    anchored=defaultdict(list)
    occ=defaultdict(list)
    weights=defaultdict(list)
    waits=defaultdict(list)
    occupied_after=defaultdict(list)
    crossing_gate=defaultdict(list)
    carries=[]
    for i,j in enumerate(jobs):
        columns=[]
        for chamber,t in j.choices:
            if j.hold_out is not None and j.hold_out<L+d: continue
            for g in range(1,min(2*n-1,(d+L+t+j.residence)//S)+1):
                deficit=max(0,P+d+L+t-g*S)
                # a,b,z count occupied robot ranks in the three ranges, including
                # both endpoint actions. Only one inbound is allowed in range C.
                for a in range(g+2):
                    if a and chamber==p.failed_chamber: continue
                    for b in range(g+2-a):
                        z=g+1-a-b
                        last=(a+b==0)
                        if z==1: continue  # at K the robot takes the last input
                        if a and b==1 and z==0: continue  # H itself is an F inbound
                        x=model.new_bool_var("")
                        columns.append(x)
                        if last:
                            lasts.append(x)
                            dues.append((j.due-P)*x)
                            if chamber==p.failed_chamber: failed_lasts.append(x)
                        if a:
                            phases[0].append((1+int(b+z==0))*x)
                        if b:
                            phases[1].append((int(a==0)+int(z==0))*x)
                        if a and z:
                            model.add(B==b).only_enforce_if(x)
                        if a and b:
                            crossing_gate[chamber].append(x)
                        if a and b+z:
                            anchored["H",-a].append(x)
                            if b and not z: anchored["H",b-1].append(x)
                        if z:
                            occupied_after[chamber].append(x)
                            anchored["K",z-1].append(x)
                            if not last:
                                anchored["K",-(a+b)].append(x)
                                carries.append((x,z,a+b,t+j.residence))
                                # Distinct rank in phase C; at most one outbound per chamber.
                        for phase,size in enumerate((a,b)):
                            if size:
                                occ[chamber,phase].append(size*x)
                        if z==0:
                            weights[chamber,2].append(deficit*x)
                            if g<=2: waits[chamber,2,g].append(deficit*x)
                            if a==0 or b==0:
                                phase=int(a==0)
                                weights[chamber,phase].append(deficit*x)
                                if g<=2: waits[chamber,phase,g].append(deficit*x)
        model.add_exactly_one(columns)
    model.add_exactly_one(lasts)
    last_f=model.new_bool_var("last_F")
    model.add(sum(failed_lasts)==last_f)
    model.add(finish<=sum(dues))
    model.add(H==sum(phases[0]))
    model.add(B==sum(phases[1]))
    for group in anchored.values(): model.add_at_most_one(group)
    for group in occupied_after.values(): model.add_at_most_one(group)
    chambers=sorted({c for j in jobs for c,_ in j.choices})
    for c in chambers:
        for s,size,idle in ((0,H,A),(1,B,V),(2,H+B,A+V)):
            occupied=(sum(occ[c,s]) if s<2 else sum(occ[c,0])+sum(occ[c,1]))
            model.add(occupied<=size)
            debt=sum(weights[c,s])
            model.add(debt<=idle)
            model.add(occupied*S+debt<=size*S+idle)
        if c!=p.failed_chamber:
            model.add(sum(occ[c,1])<=B-1+sum(crossing_gate[c])).only_enforce_if(nonempty)
    for phase,slack in enumerate((A,V,A+V)):
        singles=sum(x for c in chambers for x in waits[c,phase,1])
        doubles=[]
        for c in chambers:
            value=sum(waits[c,phase,2])
            model.add(singles+value<=slack)
            doubles.append(value)
        model.add(2*singles+sum(doubles)<=2*slack)
    for x,z,prefix_span,window in carries:
        model.add(repair+L+d+(z-2)*S+P<=finish-prefix_span*S+P+d+L+window).only_enforce_if([x,last_f])
    return model,repair

