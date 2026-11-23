"""Offline refinement of a continuing research interval, with a replayed incumbent."""

from time import perf_counter
from ..conflict_evidence import best_bound
from ..continuation import Continuation
from ..dispatch import replay_incident
from ..replay import replay_recovery
from ..terminal_exact import terminal_domain
from . import capacity, exact, frontier_witness, slot_query
from .checked_replay import CheckedIncident
from . import order_probe
from .policy import solve as previous
from .frontier_replay import FrontierIncident


def solve(incident, seconds, memory, *, baseline=False, refine=False, executable=None, energy=False, grid_executable=None, compact_scope=True):
    incident_class = CheckedIncident if refine else FrontierIncident
    if grid_executable:
        from .short_retest import PrefixIncident
        incident_class=PrefixIncident
    if memory is None:
        return previous(incident, seconds, "plain", incident_class=incident_class,grid_executable=grid_executable)
    start = perf_counter()
    end = start+seconds
    case = incident_class(**{k:getattr(incident,k) for k in Continuation.__dataclass_fields__})
    p,prefix = case.prepare()
    domain = terminal_domain(p)
    scope = memory.get("certified_scope")
    if scope:
        from .branch_probe import restrict
        domain = restrict(domain,scope["wafer"],scope["chamber"])
    cert = best_bound(p)
    scale,offset=p.scale,prefix["offset"]
    tick=lambda value: round((value-offset)*scale)
    hi=min(cert["upper_tick"],tick(memory["upper"]))
    initial=hi
    lo=-1
    best={}
    trace=[]
    def keep(plan):
        nonlocal lo,best
        q=min(t["place_start"] for t in plan["transfers"] if t["destination"]==p.failed_chamber)
        if q<lo or q>hi:
            raise ValueError(("Inconsistent witness",q,lo,hi))
        check=replay_recovery(p,q/scale,plan)
        if not check["valid"]:
            raise ValueError(check["errors"])
        packet=dict(schedule=plan,verification={k:v for k,v in check.items() if k!="trace"})
        best=dict(best=packet,verification_valid=True,witness_repair_delay_seconds=offset+q/scale,
                  verified_feasible_lower_seconds=offset+q/scale,makespan_seconds=offset+plan["makespan_tick"]/scale)
        replay_incident(case,prefix,best,packet)
        lo=q

    if memory["witness"] and not baseline:
        keep(memory["witness"]["schedule"])
        assert lo>=tick(memory["witness"]["witness_repair"])
    trace.append(dict(tool="restore_evidence",lower_tick=lo,upper_tick=hi,upper_source=memory["upper_source"]))
    def cutoff(fraction):
        return min(end,perf_counter()+fraction*seconds)
    def relax(fraction,threshold=None,split=False):
        nonlocal hi
        if perf_counter()>=end or lo>=hi:
            return
        old=hi
        hi,event=capacity.bound(p,domain,hi,cutoff(fraction),endpoints=True,threshold=threshold,prefix_split=split)
        trace.append({**event,"prev":old})
        if hi<lo:
            raise ValueError("Witness contradicted by relaxation")

    def query(q,until):
        nonlocal hi
        if perf_counter()>=until or q>hi:
            return
        st,plan,_,note=exact.fixed_query(p,domain,q,until,seed=1)
        trace.append(dict(tool="full_fixed_query",repair_tick=q,**note))
        if plan:
            keep(plan)
        elif st=="INFEASIBLE":
            hi=q-1
            if hi<lo:
                raise ValueError("Exact query contradicted a witness")

    if memory.get("rank_scope") and lo < hi and hi >= memory["rank_scope"]["floor_tick"]:
        from .resume_endpoint import query as resume_query
        # First try to attain the upper directly. Only exact residual exclusions
        # can lower it. The same historical plan is restored on both study arms.
        if executable and perf_counter()<end:
            hit=order_probe.search(p,domain,hi,hi,executable,min(end-perf_counter(),seconds*0.12))
            if hit and hit[0]>lo:
                keep(hit[1])
        if hi>lo and seconds>1 and perf_counter()<end:
            requested=hi
            st,plan,parts=resume_query(p,domain,requested,memory["rank_scope"],end,compact=compact_scope)
            if plan:
                keep(plan)
            elif st=="INFEASIBLE":
                hi=requested-1
            trace.append(dict(tool="resumed_last_inbound",repair_tick=requested,status=st,
                              partitions=parts,prior=memory["rank_scope"]["children_sha256"]))
        if hi<lo:
            raise ValueError("Scoped exclusion crossed a replayed witness")
        return dict(**best,certificate=cert,trace=trace,finite_upper_seconds=offset+hi/scale,
                    status="FINITE" if lo==hi else "UNKNOWN",makespan_optimal=False,
                    latest_repair_delay_seconds=offset+hi/scale if lo==hi else None)

    if scope:
        # The archived, independently checked complement is infeasible even at zero.
        # Both comparison arms spend their budget on the one remaining zero-delay branch.
        if energy and lo<0:
            from . import age_network,flow_price
            period=domain[1]+domain[2]+2*domain[3]
            quantum=next(v for v in range(max(1,period//3),0,-1) if period%v==0)
            bounds,rows,size=age_network.matrix(domain,quantum)
            proof=flow_price.solve_table(bounds,rows,end)
            trace.append(dict(tool="joint_age_flow_dual",scope=scope,**size,**proof))
            if proof["status"]=="INFEASIBLE": hi=-1
        if hi>=0 and lo<0 and executable:
            witness=order_probe.search(p,domain,0,hi,executable,min(end-perf_counter(),seconds*0.16))
            if witness:
                keep(witness[1])
        if hi>=0 and lo<0 and perf_counter()<end and seconds>1:
            status,plan,parts=slot_query.query(p,domain,0,end,enhanced=energy)
            if plan:
                keep(plan)
            elif status=="INFEASIBLE":
                hi=-1
            trace.append(dict(tool="fixed_zero_remaining_route",scope=scope,status=status,partitions=parts))
        return dict(**best,certificate=cert,trace=trace,
            finite_upper_seconds=offset+hi/scale if hi>=0 else None,
            status="INFEASIBLE_AT_ZERO" if hi<0 else "FINITE" if lo==hi else "UNKNOWN",
            latest_repair_delay_seconds=offset+hi/scale if lo==hi and hi>=0 else None,
            makespan_optimal=False)

    if baseline:
        old=previous(case,max(0,end-perf_counter()),"plain",incumbent=memory["witness"],incident_class=FrontierIncident)
        trace.extend(old["trace"])
        if old.get("verification_valid"):
            lo=tick(old["witness_repair_delay_seconds"])
            best={k:old[k] for k in ("best","verification_valid","witness_repair_delay_seconds",
                                      "verified_feasible_lower_seconds","makespan_seconds")}
        if memory["witness"] and lo<tick(memory["witness"]["witness_repair"]):
            raise ValueError("Baseline dropped archived witness")
        if old["status"]=="INFEASIBLE_AT_ZERO":
            hi=-1
        elif old.get("finite_upper_seconds") is not None:
            hi=min(hi,tick(old["finite_upper_seconds"]))
    else:
        short=seconds<=1
        if refine and executable and hi > lo:
            q = 0 if lo < 0 else (lo+hi+1)//2
            allocation = min(end-perf_counter(),seconds*(0.16 if short else 0.12))
            candidate = order_probe.search(p,domain,q,hi,executable,allocation)
            if candidate and candidate[0] > lo:
                keep(candidate[1])
            trace.append(dict(tool="construct_transfer_order",repair_tick=q,
                              attained=candidate[0] if candidate else None))
        if refine and not short and hi > lo:
            q = 0 if lo < 0 else hi
            st, plan, partitions = slot_query.query(p, domain, q, cutoff(0.36), enhanced=energy)
            trace.append(dict(tool="terminal_rank_partitions",repair_tick=q,status=st,partitions=partitions))
            if plan:
                keep(plan)
            elif st == "INFEASIBLE":
                hi = q-1
                if hi < lo:
                    raise ValueError("Rank partition result contradicted a verified schedule")
        # Test attainability of the archived upper, then optimize the relaxation.
        relax(0.20 if short else 0.06,hi)
        relax(0.30 if short else 0.27)
        # A feasibility query for half the open interval often proves more than
        # branch-and-bound maximization when the relaxation itself has little time.
        if not short and hi>lo+1:
            relax(0.09,(hi+max(lo,0)+1)//2,split=True)
        if lo < 0 and not short:
            query(0,cutoff(0.24))
        if hi>lo and perf_counter()<end:
            until=end if short else cutoff(0.21)
            incumbent=(lo,best["best"]["schedule"]) if best else None
            candidate,count=frontier_witness.improve(p,domain,hi,until,incumbent)
            before=lo
            if candidate and candidate[0]>lo:
                keep(candidate[1])
            trace.append(dict(tool="witness_order_search",before=before,after=lo,attempts=count))
        if not short and hi>lo and perf_counter()<end:
            query(hi if lo>=0 or hi<initial else 0,end)
    if hi<lo:
        raise ValueError("Crossed frontier bounds")
    return dict(**best,certificate=cert,trace=trace,finite_upper_seconds=offset+hi/scale if hi>=0 else None,
                status="INFEASIBLE_AT_ZERO" if hi<0 else "FINITE" if hi==lo else "UNKNOWN",
                latest_repair_delay_seconds=offset+hi/scale if hi>=0 and hi==lo else None,
                makespan_optimal=False)
