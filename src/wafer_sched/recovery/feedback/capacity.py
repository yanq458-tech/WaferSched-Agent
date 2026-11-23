"""Necessary per-chamber transfer-rank and processing workloads before the last source pick."""

import math
from time import perf_counter
from ortools.sat.python import cp_model


def bound(p, domain, cap, deadline, *, endpoints=False, threshold=None, prefix_split=False):
    jobs, P, L, d = domain
    s = P + L + 2 * d
    initial = p.snapshot["robot"]["position"]
    first = min(max(j.ready, 0 if j.source == initial else d) for j in jobs)
    model = cp_model.CpModel()
    q = model.new_int_var(0, cap, "repair")
    chambers = {c for j in jobs for c, _ in j.choices}
    pending = {c: [] for c in chambers}
    ranks = {c: [] for c in chambers}
    extras = {c: [] for c in chambers}
    used = {c: [] for c in chambers}
    last_at = {c: [] for c in chambers}
    tails = []
    completed = {c: [] for c in chambers}
    adjacent_idle = []
    two_gap_idle = {c: [] for c in chambers}
    lasts = []
    last_deadlines = []
    n = len(jobs)
    for j in jobs:
        last = model.new_bool_var("last_" + j.wafer)
        lasts.append(last)
        last_deadlines.append((j.due - P) * last)
        options = [last]
        last_choices = []
        for c, t in j.choices:
            carry = model.new_bool_var("pending")
            if endpoints:
                selected_last = model.new_bool_var("last_destination")
                last_choices.append(selected_last)
                last_at[c].append(selected_last)
                tails.append((c, carry, t + j.residence))
            pending[c].append(carry)
            ranks[c].append(carry)
            used[c].append(carry)
            options.append(carry)
            for g in range(1, min(2 * n - 2, (d + L + t + j.residence) // s) + 1):
                put = model.new_bool_var("completed")
                options.append(put)
                used[c].append(put)
                ranks[c].append((g + 1) * put)
                idle = max(0, P + d + L + t - g * s) * put
                extras[c].append(idle)
                if prefix_split:
                    completed[c].append((g,max(0,P+d+L+t-g*s),put))
                if endpoints and g == 1:
                    adjacent_idle.append(idle)
                if endpoints and g == 2:
                    two_gap_idle[c].append(idle)
        model.add_exactly_one(options)
        if endpoints:
            model.add(sum(last_choices) == last)
    model.add_exactly_one(lasts)
    D = sum(last_deadlines)
    K = 2 * (n - 1) - sum(v for vals in pending.values() for v in vals)
    slack = D - first - K * s
    model.add(slack >= 0)
    positions = []
    tail_ranks = {}
    pickup_ranks = {}
    for c in sorted(chambers):
        model.add(sum(pending[c]) <= 1)
        count = sum(ranks[c])
        extra = sum(extras[c])
        model.add(count <= K)
        model.add(extra <= slack)
        model.add(s * count + extra <= D - first)
        if endpoints:
            # Transfer ranks before the last source pick: each active chamber's first
            # and last event occupy distinct robot slots, even if the arm waits.
            present = model.new_bool_var("prefix_chamber_used")
            model.add(sum(used[c]) > 0).only_enforce_if(present)
            model.add(sum(used[c]) == 0).only_enforce_if(~present)
            head = model.new_int_var(0, 2*n, "prefix_head")
            tail = model.new_int_var(0, 2*n, "prefix_tail")
            for other, h, z in positions:
                model.add(head != h).only_enforce_if([present, other])
                model.add(tail != z).only_enforce_if([present, other])
            positions.append((present, head, tail))
            tail_ranks[c] = tail
            model.add(head + count + tail <= K).only_enforce_if(present)
            model.add(first + s*(head + count + tail) + extra <= D).only_enforce_if(present)
            model.add(sum(pending[c]) + sum(last_at[c]) <= 1)
            if c == p.failed_chamber:
                model.add(q - P - d + s*(count + tail) + extra <= D).only_enforce_if(present)
            waiting = model.new_bool_var("pending_on_chamber")
            model.add(sum(pending[c]) == waiting)
            rank = model.new_int_var(0, n, "pending_unload_rank")
            for other, other_rank in pickup_ranks.values():
                model.add(rank != other_rank).only_enforce_if([waiting, other])
            pickup_ranks[c] = (waiting, rank)
        if c == p.failed_chamber:
            active = model.new_bool_var("failed_chamber_used_in_prefix")
            model.add(sum(used[c]) == 0).only_enforce_if(~active)
            model.add(s * count + extra <= D - q + P + d).only_enforce_if(active)
    if prefix_split:
        # A gap between consecutive paired moves cannot overlap a two-gap pair:
        # the latter has only one interior action. Within one chamber pairs are disjoint.
        singles = sum(adjacent_idle)
        model.add(singles <= slack)
        for group in two_gap_idle.values():
            model.add(singles + sum(group) <= slack)
        model.add(2*singles + sum(x for group in two_gap_idle.values() for x in group) <= 2*slack)
    if endpoints:
        for c, on, window in tails:
            # Pending wafer's placement ends no later than A-d-tail*s. Its
            # unload ends no earlier than A+s+rank*s+P, for last source time A.
            k = pickup_ranks[c][1]
            tail = tail_ranks[c]
            model.add((1+k+tail)*s + P+d <= window).only_enforce_if(on)
            for is_last_failed in last_at.get(p.failed_chamber, []):
                model.add(q+L+d+k*s+P <= D-d-tail*s+window).only_enforce_if([on,is_last_failed])
    if prefix_split and p.failed_chamber in used:
        # Before the first failed-chamber load, every other transfer goes to or
        # from a healthy chamber. Completed H pairs enclose disjoint rank gaps.
        failed = p.failed_chamber
        used_failed = model.new_bool_var("failed_used_before_last_source")
        model.add(sum(used[failed]) >= 1).only_enforce_if(used_failed)
        model.add(sum(used[failed]) == 0).only_enforce_if(~used_failed)
        for healthy in sorted(chambers-{failed}):
            others = chambers-{healthy,failed}
            other_moves = sum(sum(pending[c])+2*sum(v for _,_,v in completed[c]) for c in sorted(others))
            early, enclosed, early_idle = [], [], []
            for g, idle, chosen in completed[healthy]:
                before = model.new_bool_var("completed_before_first_failed_load")
                model.add(before <= chosen)
                early.append(before)
                enclosed.append((g-1)*before)
                if g == 1:
                    early_idle.append(idle*before)
            model.add(sum(enclosed) <= other_moves)
            max_prefix = 2*sum(early)+1+other_moves
            model.add(K <= max_prefix).only_enforce_if(~used_failed)
            singles_after = sum(idle*v for c in (failed,healthy) for g,idle,v in completed[c] if g==1)-sum(early_idle)
            model.add(q+(K-max_prefix)*s-P-d+singles_after <= D).only_enforce_if(used_failed)
    if threshold is None:
        model.maximize(q)
    else:
        model.add(q >= threshold)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = max(0, deadline - perf_counter())
    st = solver.solve(model)
    if st == cp_model.MODEL_INVALID:
        raise ValueError(model.validate())
    upper = (
        (min(cap, math.ceil(solver.best_objective_bound)) if threshold is None else cap)
        if st in (cp_model.FEASIBLE, cp_model.OPTIMAL)
        else (-1 if threshold is None else min(cap,threshold-1))
        if st == cp_model.INFEASIBLE
        else cap
    )
    return upper, dict(
        tool="first_failed_load_split" if prefix_split else "prefix_endpoints" if endpoints else "prefix_capacity_relaxation",
        **({"threshold": threshold} if threshold is not None else {}),
        status=solver.status_name(st),
        prior_upper=cap,
        upper_tick=upper,
        branches=solver.num_branches,
        seconds=solver.wall_time,
    )
