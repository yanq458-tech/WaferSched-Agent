from time import perf_counter

import pytest

from wafer_sched.recovery.conflict_evidence import best_bound
from wafer_sched.recovery.rank_cover import cover_rank
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.short_budget import PreparedIncident
from wafer_sched.recovery.study_data import terminal_case
from wafer_sched.recovery.tail_ranks import solve_rank
from wafer_sched.recovery.terminal_exact import terminal_domain


def test_detached_snapshots_and_exact_clock():
    incident = terminal_case(4, 2)
    fast = PreparedIncident(**vars(incident))
    original, new = incident.at_fault(), fast.at_fault()
    assert original.trace == new.trace
    assert original.snapshot() == new.snapshot()
    obs = new.snapshot()
    wafer = next(iter(obs["wafers"].values()))
    wafer["processing_records"].append({"end": -999})
    assert original.snapshot() == new.snapshot()
    p, _ = fast.prepare()
    scale = p.scale
    p.clock_scale = 3 * scale
    assert p.scale == 3 * scale
    p2, _ = fast.prepare()
    assert p2.scale == scale


@pytest.mark.parametrize("n,seed", [(2, 2), (2, 4), (3, 2), (3, 4), (4, 2), (4, 4)])
def test_complete_cover_against_independent_cp_rank_model(n, seed):
    p, _ = terminal_case(n, seed).prepare()
    dom = terminal_domain(p)
    cap = best_bound(p)["upper_tick"]
    for rank in range(n - 1, 2 * n - 1):
        plan, out = cover_rank(p, dom, rank, cap, 0, perf_counter() + 10)
        _, exact = solve_rank(p, dom, rank, cap, 0, perf_counter() + 10)
        assert out["status"] == exact["status"]
        if plan:
            q = out["repair_tick"]
            assert q == exact["repair_tick"]
            assert replay_recovery(p, q / p.scale, plan)["valid"]
            optimal, _ = solve_rank(
                p, dom, rank, q, q, perf_counter() + 10, fixed=True, minimize=True
            )
            assert optimal["makespan_tick"] == plan["makespan_tick"]


def test_interrupted_cover_retains_conservative_bound():
    p, _ = terminal_case(8, 4).prepare()
    cap = best_bound(p)["upper_tick"]
    plan, row = cover_rank(p, terminal_domain(p), 10, cap, 0, perf_counter() - 1)
    assert row["status"] in {"FEASIBLE", "UNKNOWN"}
    if plan:
        assert row["objective_upper"] == cap
        assert replay_recovery(p, row["repair_tick"] / p.scale, plan)["valid"]
