"""Necessary per-chamber transfer-rank and processing workloads before the last source pick."""

import math
from time import perf_counter
from ortools.sat.python import cp_model


def bound(p, domain, cap, deadline):
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
    lasts = []
    last_deadlines = []
    n = len(jobs)
    for j in jobs:
        last = model.new_bool_var("last_" + j.wafer)
        lasts.append(last)
        last_deadlines.append((j.due - P) * last)
        options = [last]
        for c, t in j.choices:
            carry = model.new_bool_var("pending")
            pending[c].append(carry)
            ranks[c].append(carry)
            used[c].append(carry)
            options.append(carry)
            for g in range(1, min(2 * n - 2, (d + L + t + j.residence) // s) + 1):
                put = model.new_bool_var("completed")
                options.append(put)
                used[c].append(put)
                ranks[c].append((g + 1) * put)
                extras[c].append(max(0, P + d + L + t - g * s) * put)
        model.add_exactly_one(options)
    model.add_exactly_one(lasts)
    D = sum(last_deadlines)
    K = 2 * (n - 1) - sum(v for vals in pending.values() for v in vals)
    slack = D - first - K * s
    model.add(slack >= 0)
    for c in sorted(chambers):
        model.add(sum(pending[c]) <= 1)
        count = sum(ranks[c])
        extra = sum(extras[c])
        model.add(count <= K)
        model.add(extra <= slack)
        model.add(s * count + extra <= D - first)
        if c == p.failed_chamber:
            active = model.new_bool_var("failed_chamber_used_in_prefix")
            model.add(sum(used[c]) == 0).only_enforce_if(~active)
            model.add(s * count + extra <= D - q + P + d).only_enforce_if(active)
    model.maximize(q)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = max(0, deadline - perf_counter())
    st = solver.solve(model)
    if st == cp_model.MODEL_INVALID:
        raise ValueError(model.validate())
    upper = (
        min(cap, math.ceil(solver.best_objective_bound))
        if st in (cp_model.FEASIBLE, cp_model.OPTIMAL)
        else -1
        if st == cp_model.INFEASIBLE
        else cap
    )
    return upper, dict(
        tool="prefix_capacity_relaxation",
        status=solver.status_name(st),
        prior_upper=cap,
        upper_tick=upper,
        branches=solver.num_branches,
        seconds=solver.wall_time,
    )
