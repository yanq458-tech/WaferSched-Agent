import os
from pathlib import Path
import subprocess
from time import perf_counter

import pytest
from wafer_sched.recovery.feedback import age_network,flow_price,short_retest,slot_query
from wafer_sched.recovery.feedback.target_queries import Continuation,terminal_domain,load
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.dispatch import replay_incident


def test_fault_prefix_is_independent_and_still_validated():
    case=short_retest.PrefixIncident.from_dict(terminal_case(3,4).to_dict())
    sim=case.at_fault()
    original=sim.snapshot()
    sim.state.time+=1000
    sim.trace[0]["event"]="tampered"
    clone=case.at_fault()
    assert clone.snapshot()==original
    assert clone.trace[0]["event"]!="tampered"
    clone.state.wafers.pop(next(iter(clone.state.wafers)))
    with pytest.raises(RuntimeError):
        clone._assert_state()
    assert case.at_fault().snapshot()==original


@pytest.mark.parametrize("q",[0,10,31])
def test_gate_rounding_contains_feasible_exact_orders(q):
    case=terminal_case(3,4)
    p,_=case.prepare()
    domain=terminal_domain(p)
    exact,plan,_=slot_query.query(p,domain,q,perf_counter()+10)
    assert exact!="UNKNOWN"
    bounds,table,_=age_network.matrix(domain,6,repair=q,failed=p.failed_chamber)
    result=flow_price.solve_table(bounds,table,perf_counter()+10)
    if plan:
        assert replay_recovery(p,q/p.scale,plan)["valid"] and result["status"]!="INFEASIBLE"


def test_compiled_cover_retimes_and_replays(tmp_path):
    csc=Path(os.environ.get("WINDIR",""))/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not csc.is_file(): pytest.skip("Windows Framework compiler required")
    root=Path(__file__).resolve().parents[2]
    exe=tmp_path/"cover.exe"
    subprocess.run([str(csc),"/nologo","/optimize+","/out:"+str(exe),
                    str(root/"scripts/TerminalGridCover.cs")],check=True)
    src=root/"results/recovery/feedback-study/final-holdout/inputs/blind-24-m-f2.json"
    case=short_retest.PrefixIncident.from_dict(load(src))
    p,h=case.prepare()
    from wafer_sched.recovery.conflict_evidence import best_bound
    q=best_bound(p)["upper_tick"]
    schedule=short_retest.grid_hint(p,terminal_domain(p),q,perf_counter()+3,exe)
    assert schedule
    original=Continuation.from_dict(load(src))
    suffix,prefix=original.prepare()
    check=replay_recovery(suffix,q/suffix.scale,schedule)
    assert check["valid"]
    replay_incident(original,prefix,dict(witness_repair_delay_seconds=q/suffix.scale+prefix["offset"],
                    makespan_seconds=schedule["makespan_tick"]/suffix.scale+prefix["offset"]),dict(verification=check))

