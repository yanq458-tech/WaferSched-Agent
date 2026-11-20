"""Exact uniform-travel terminal suffix. See docs/terminal-proofs.md for equivalence."""

from dataclasses import replace
from time import perf_counter

from ortools.sat.python import cp_model

from ..cpsat_model import ticks
from .dispatch import replay_incident
from .healthy_witness import terminal_jobs
from .model import RecoveryModel, dimensions
from .solver import read_witness


def terminal_domain(p):
    jobs = terminal_jobs(p, healthy_only=False)
    if not jobs:
        return None
    scale, robot = p.scale, p.config.robot
    locations = {p.snapshot["robot"]["position"], "OUT"}
    for job in jobs:
        locations.add(job.source)
        locations.update(c for c, _ in job.choices)
    distances = {ticks(robot.travel(a, b), scale) for a in locations for b in locations if a != b}
    if len(distances) != 1 or any(robot.travel(a, a) != 0 for a in locations):
        return None
    travel = distances.pop()
    if any(duration < travel for job in jobs for _, duration in job.choices):
        return None
    return jobs, ticks(robot.pick_seconds, scale), ticks(robot.place_seconds, scale), travel


def workload(domain):
    jobs, pick, place, travel = domain
    due_jobs = [j for j in jobs if j.due is not None]
    for due in sorted({j.due for j in due_jobs}):
        subset = [j for j in due_jobs if j.due <= due]
        targets = sorted({c for j in subset for c, _ in j.choices})
        inbound = len(subset) - 1
        outbound = max(0, inbound - len(targets))
        required = (inbound + outbound) * (pick + place + 2 * travel) + pick
        if required > due:
            return dict(
                kind="terminal_capacity_workload",
                wafers=[j.wafer for j in subset],
                targets=targets,
                prior_loads=inbound,
                prior_unloads=outbound,
                earliest_last_pick_end_tick=required,
                deadline_tick=due,
            )
    return None


def verify_workload(p, certificate):
    domain = terminal_domain(p)
    if domain is None or not isinstance(certificate, dict):
        return False
    jobs, pick, place, travel = domain
    ids = certificate.get("wafers")
    deadline = certificate.get("deadline_tick")
    if (
        certificate.get("kind") != "terminal_capacity_workload"
        or not isinstance(ids, list)
        or not ids
        or not all(isinstance(w, str) for w in ids)
        or type(deadline) is not int
    ):
        return False
    selected = [j for j in jobs if j.wafer in ids]
    if len(selected) != len(ids) or any(j.due is None or j.due > deadline for j in selected):
        return False
    targets = {c for job in selected for c, _ in job.choices}
    loads = len(selected) - 1
    unloads = loads - min(loads, len(targets))
    transfers = loads + unloads
    earliest = pick * (transfers + 1) + (place + 2 * travel) * transfers
    return (
        certificate.get("targets") == sorted(targets)
        and certificate.get("prior_loads") == loads
        and certificate.get("prior_unloads") == unloads
        and certificate.get("earliest_last_pick_end_tick") == earliest
        and earliest > deadline
    )


def pending_conflict(p, domain):
    """All repair times: necessary total residence across the last source transfer."""
    jobs, pick, place, travel = domain
    if any(j.due is None or j.residence is None for j in jobs):
        return None
    period = pick + place + 2 * travel
    if period <= 0:
        return None
    initial = p.snapshot["robot"]["position"]
    first = min(max(0, j.ready, travel if initial != j.source else 0) for j in jobs)
    deadline = max(j.due for j in jobs)
    prior = (deadline - pick - first) // period
    pending = max(0, 2 * (len(jobs) - 1) - prior)
    if not 1 <= pending < len(jobs):
        return None
    windows = sorted((max(t for _, t in j.choices) + j.residence for j in jobs), reverse=True)
    available = sum(windows[:pending])
    required = pending * (pending * period + pick + travel)
    if available >= required:
        return None
    return dict(
        kind="terminal_pending_residence",
        first_possible_start_tick=first,
        last_source_due_tick=deadline,
        prior_transfers_at_most=prior,
        min_pending=pending,
        top_windows_tick=windows[:pending],
        available_sum_tick=available,
        required_sum_tick=required,
    )


def verify_pending(p, certificate):
    """Check the two ordered time sums on the input, independently of the search."""
    domain = terminal_domain(p)
    if domain is None or not isinstance(certificate, dict):
        return False
    jobs, pick, place, d = domain
    k = certificate.get("min_pending")
    if (
        type(k) is not int
        or not 1 <= k < len(jobs)
        or any(j.due is None or j.residence is None for j in jobs)
    ):
        return False
    period = pick + place + 2 * d
    if period <= 0:
        return False
    due = max(j.due for j in jobs)
    initial = p.snapshot["robot"]["position"]
    first = min(max(j.ready, 0 if j.source == initial else d) for j in jobs)
    moves = (due - pick - first) // period
    windows = sorted((max(t + j.residence for _, t in j.choices) for j in jobs), reverse=True)[:k]
    # Relative to the last source pick start. Pairing is unnecessary after summation.
    latest_loads = sum(-d - i * period for i in range(k))
    earliest_pick_ends = sum(period + pick + i * period for i in range(k))
    required = earliest_pick_ends - latest_loads
    return (
        certificate.get("kind") == "terminal_pending_residence"
        and k == 2 * (len(jobs) - 1) - moves
        and certificate.get("first_possible_start_tick") == first
        and certificate.get("last_source_due_tick") == due
        and certificate.get("prior_transfers_at_most") == moves
        and certificate.get("top_windows_tick") == windows
        and certificate.get("available_sum_tick") == sum(windows)
        and certificate.get("required_sum_tick") == required
        and sum(windows) < required
    )


def last_load_bound(p, domain):
    """Split on a mandatory failed load followed by another source pickup or not."""
    jobs, pick, place, travel = domain
    if any(j.due is None for j in jobs):
        return None
    period = pick + place + 2 * travel
    candidates = []
    for mandatory in jobs:
        if {c for c, _ in mandatory.choices} != {p.failed_chamber}:
            continue
        others = [j for j in jobs if j != mandatory]
        if not others or period <= 0:
            continue
        # If q > D_m, every terminal occupied when m is picked must be healthy.
        upper_other_last = max(j.due for j in others) - place - travel - pick
        split = max(mandatory.due, upper_other_last)
        start = min(
            max(0, j.ready, travel if p.snapshot["robot"]["position"] != j.source else 0)
            for j in jobs
        )
        prior_max = (mandatory.due - pick - start) // period
        pending = max(0, 2 * len(others) - prior_max)
        if not pending:
            continue
        healthy = {c for j in others for c, _ in j.choices if c != p.failed_chamber}
        if pending > len(healthy) or any(
            all(c == p.failed_chamber for c, _ in j.choices) for j in others
        ):
            upper = split
        else:
            if any(j.residence is None for j in others):
                continue
            slack = sorted(
                (
                    max(t for c, t in j.choices if c != p.failed_chamber) + j.residence
                    for j in others
                ),
                reverse=True,
            )
            upper = max(
                split,
                mandatory.due
                - 2 * pick
                - 2 * travel
                - place
                + sum(slack[:pending]) // pending
                - period * (pending - 1),
            )
        candidates.append(
            dict(
                kind="last_mandatory_load",
                wafer=mandatory.wafer,
                max_prior_transfers=prior_max,
                min_pending=pending,
                split_tick=split,
                upper_tick=upper,
            )
        )
    return min(candidates, key=lambda c: c["upper_tick"], default=None)


def build(p, domain, cap):
    jobs, pick, place, travel = domain
    scale = p.scale
    vertices, constant, sentinel_base = dimensions(p)
    limit = min(cap, sentinel_base + 1) if cap is not None else sentinel_base + 1
    horizon = vertices * (constant + sentinel_base + 2)
    if horizon >= 2**50:
        return None
    model = cp_model.CpModel()
    q = model.new_int_var(0, max(0, limit), "repair")
    if limit < 0:
        model.add_bool_or([])
    locations = ("OUT", *(c.chamber_id for c in p.config.chambers))
    idx = {c: i for i, c in enumerate(locations)}
    robot_intervals, chamber_intervals, tasks, processes, ends = [], {}, [], [], []
    initial = p.snapshot["robot"]["position"]
    starts, loads = {}, {}
    for j in jobs:
        a, b, c, finish, dest = [
            model.new_int_var(0, horizon, f"{j.wafer}_{key}")
            for key in ("pick", "place", "unload", "ready", "terminal")
        ]
        starts[j.wafer], loads[j.wafer] = a, b
        model.add(a >= max(j.ready, travel if initial != j.source else 0))
        if j.due is not None:
            model.add(a + pick <= j.due)
        model.add(b >= a + pick + travel)
        if j.hold_in is not None:
            model.add(b + place <= a + pick + j.hold_in)
        if j.hold_out is not None and travel + place > j.hold_out:
            model.add_bool_or([])
        model.add(c >= finish)
        if j.residence is not None:
            model.add(c + pick <= finish + j.residence)
        length = model.new_int_var(0, horizon, f"occupy_{j.wafer}")
        model.add(length == c + pick - b)
        choices = []
        for chamber, duration in j.choices:
            present = model.new_bool_var(f"{j.wafer}_{chamber}")
            choices.append(present)
            model.add(dest == idx[chamber]).only_enforce_if(present)
            model.add(finish == b + place + duration).only_enforce_if(present)
            if chamber == p.failed_chamber:
                model.add(b >= q).only_enforce_if(present)
            chamber_intervals.setdefault(chamber, []).append(
                model.new_optional_interval_var(
                    b, length, c + pick, present, f"capacity_{j.wafer}_{chamber}"
                )
            )
        model.add_exactly_one(choices)
        size = model.new_int_var(0, horizon + travel, f"loaded_{j.wafer}")
        robot_intervals.append(model.new_interval_var(a, size, b + place + travel, "in_" + j.wafer))
        out_start = c + pick + travel
        end = out_start + place
        robot_intervals.append(
            model.new_fixed_size_interval_var(c, pick + 2 * travel + place, "out_" + j.wafer)
        )
        ends.append(end)
        for stage, source, target, ps, ls in (
            (j.stage, idx[j.source], dest, a, b),
            (j.stage + 1, dest, idx["OUT"], c, out_start),
        ):
            tasks.append(
                dict(
                    wafer_id=j.wafer,
                    stage=stage,
                    source=source,
                    destination=target,
                    pick_start=ps,
                    pick_end=ps + pick,
                    place_start=ls,
                    place_end=ls + place,
                    initially_carried=False,
                )
            )
        processes.append(
            dict(wafer_id=j.wafer, stage=j.stage, chamber=dest, start=b + place, end=finish)
        )
    packing = last_load_bound(p, domain)
    if packing:
        model.add(q <= packing["upper_tick"])
        late = model.new_bool_var("after_split")
        model.add(q > packing["split_tick"]).only_enforce_if(late)
        model.add(q <= packing["split_tick"]).only_enforce_if(~late)
        for j in jobs:
            if j.wafer != packing["wafer"]:
                model.add(
                    loads[j.wafer] + place + travel <= starts[packing["wafer"]]
                ).only_enforce_if(late)
    model.add_no_overlap(robot_intervals)
    for intervals in chamber_intervals.values():
        model.add_no_overlap(intervals)
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, ends)
    model.maximize(q)
    return RecoveryModel(
        model, tasks, processes, locations, makespan, scale, horizon, sentinel_base, q
    )


def build_zero(p, domain):
    """Satisfaction at zero, with all original deadlines and neither arithmetic cut."""
    jobs, *timing = domain
    relaxed = ([replace(j, due=None) for j in jobs], *timing)
    bundle = build(p, relaxed, None)
    for job, task in zip(jobs, bundle.tasks[::2], strict=True):
        if job.due is not None:
            bundle.model.add(task["pick_end"] <= job.due)
    bundle.model.add(bundle.repair_variable == 0)
    bundle.model.clear_objective()
    return bundle


def solve_terminal(case, p, prefix, domain, cert, deadline):
    cap = cert["upper_tick"] if cert else None
    bundle = build(p, domain, cap)
    if bundle is None:
        return None
    offset, scale = prefix["offset"], bundle.scale
    out = dict(
        status="UNKNOWN",
        makespan_optimal=False,
        verification_valid=False,
        trace=[],
        finite_upper_seconds=None if cap is None else offset + cap / scale,
    )
    packing = last_load_bound(p, domain)
    if packing:
        out["trace"].append({"tool": "terminal_last_load_bound", **packing})
        value = offset + packing["upper_tick"] / scale
        out["finite_upper_seconds"] = (
            min(value, out["finite_upper_seconds"]) if cap is not None else value
        )

    budget_left = max(0, deadline - perf_counter())
    short_budget = budget_left <= 1
    tight_packing = packing and packing["upper_tick"] == packing["split_tick"]

    def query(objective, fraction=1):
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        reserve = 0.65 if short_budget else 1
        solver.parameters.max_time_in_seconds = (
            max(0, deadline - perf_counter()) * fraction * reserve
        )
        status = solver.solve(bundle.model)
        if status == cp_model.MODEL_INVALID:
            raise ValueError(bundle.model.validate() or "Invalid terminal model")
        out["trace"].append(
            dict(
                tool=objective,
                status=solver.status_name(status),
                branches=solver.num_branches,
                seconds=solver.wall_time,
            )
        )
        return solver, status

    solver, status = query("terminal_maximize_repair", 0.30 if tight_packing else 1)
    fixed_zero = False
    if tight_packing and status == cp_model.UNKNOWN and perf_counter() < deadline:
        # Earlier repair only releases loads. Infeasibility at zero excludes all q.
        bundle = build_zero(p, domain)
        solver, status = query("terminal_zero_after_no_witness")
        fixed_zero = True
    elif tight_packing and status == cp_model.FEASIBLE and perf_counter() < deadline:
        bundle.model.add(bundle.repair_variable >= solver.value(bundle.repair_variable))
        trial, verdict = query("terminal_continue_from_incumbent")
        if verdict == cp_model.INFEASIBLE:
            raise RuntimeError("Lost feasible repair incumbent")
        if verdict in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver, status = trial, verdict
    if status == cp_model.INFEASIBLE:
        out["status"] = "INFEASIBLE_AT_ZERO"
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return out
    q = solver.value(bundle.repair_variable)
    delay = q / scale
    if fixed_zero:
        if out["finite_upper_seconds"] == offset:
            out.update(status="FINITE", latest_repair_delay_seconds=offset)
    elif q == bundle.finite_cap + 1:
        out["status"] = "UNBOUNDED"
    else:
        upper = int(solver.best_objective_bound)
        if upper <= bundle.finite_cap:
            value = offset + upper / scale
            out["finite_upper_seconds"] = (
                min(value, out["finite_upper_seconds"])
                if out["finite_upper_seconds"] is not None
                else value
            )
        if q == upper or status == cp_model.OPTIMAL:
            out.update(status="FINITE", latest_repair_delay_seconds=offset + delay)

    def witness(s):
        schedule, check = read_witness(p, bundle, s, delay)
        if not check["valid"]:
            raise RuntimeError(check["errors"])
        best = dict(
            schedule=schedule, verification={k: v for k, v in check.items() if k != "trace"}
        )
        out.update(
            verification_valid=True,
            best=best,
            verified_feasible_lower_seconds=offset + delay,
            witness_repair_delay_seconds=offset + delay,
            makespan_seconds=offset + schedule["makespan_tick"] / scale,
        )
        replay_incident(case, prefix, out, best)

    witness(solver)
    if out["status"] == "FINITE" and perf_counter() < deadline:
        bundle.model.add(bundle.repair_variable == q)
        bundle.model.add(bundle.makespan <= solver.value(bundle.makespan))
        bundle.model.minimize(bundle.makespan)
        second, status = query("terminal_minimize_makespan")
        if status == cp_model.INFEASIBLE:
            raise RuntimeError("Boundary witness contradicted")
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            witness(second)
            out["makespan_optimal"] = status == cp_model.OPTIMAL
    return out
