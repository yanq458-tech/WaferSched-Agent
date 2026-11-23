"""Fixed-repair satisfaction with necessary chamber circulation and late-tail cuts."""

from time import perf_counter
from ortools.sat.python import cp_model
from .. import terminal_exact
from ..solver import read_witness


def fixed_query(p, domain, q, deadline, *, seed=0):
    jobs, P, L, d = domain
    bundle = terminal_exact.build(p, domain, q)
    if bundle is None:
        return "UNKNOWN", None, None, dict(reason="model_horizon")
    model = bundle.model
    model.clear_objective()
    model.add(bundle.repair_variable == q)
    machines = {}
    for i, j in enumerate(jobs):
        load, unload = bundle.tasks[2 * i : 2 * i + 2]
        # From one outgoing pick completion to the next placement in this same chamber:
        # loaded travel to OUT, placement, empty travel, pick, loaded travel.
        latest = unload["pick_end"] + 2 * d + d + P + L
        b = load["place_start"]
        size = model.new_int_var(0, bundle.horizon + 3 * d + P + L, "extended_span")
        model.add(size == latest - b)
        for c, _ in j.choices:
            on = model.new_bool_var("selected")
            ix = bundle.locations.index(c)
            model.add(load["destination"] == ix).only_enforce_if(on)
            model.add(load["destination"] != ix).only_enforce_if(~on)
            machines.setdefault(c, []).append(
                model.new_optional_interval_var(b, size, latest, on, "circulation")
            )
    for group in machines.values():
        model.add_no_overlap(group)
    separated = 0
    for i, last in enumerate(jobs):
        if any(c != p.failed_chamber for c, t in last.choices):
            continue
        if any(q + L + d + P <= j.due for j in jobs if j != last):
            continue
        start = bundle.tasks[2 * i]["pick_start"]
        for k, j in enumerate(jobs):
            if i == k:
                continue
            model.add(bundle.tasks[2 * k]["place_end"] + d <= start)
            if q + L + d + P > last.due - P - d + max(t for c, t in j.choices) + j.residence:
                model.add(bundle.tasks[2 * k + 1]["place_end"] + d <= start)
                separated += 1
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = max(0, deadline - perf_counter())
    st = solver.solve(model)
    if st == cp_model.MODEL_INVALID:
        raise ValueError(model.validate())
    status = solver.status_name(st)
    note = dict(
        status=status,
        branches=solver.num_branches,
        seconds=solver.wall_time,
        cleared_before_last=separated,
    )
    if st not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return status, None, None, note
    plan, check = read_witness(p, bundle, solver, q / p.scale)
    return status, plan, check, note
