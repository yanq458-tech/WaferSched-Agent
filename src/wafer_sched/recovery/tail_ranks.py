"""Bounds from terminal transfer ranks, and a complete fixed-last-rank CP subproblem."""

from itertools import permutations

from .dispatch import replay_incident
from .replay import replay_recovery
from time import perf_counter

from ortools.sat.python import cp_model

from .terminal_exact import last_load_bound


def compatible_slots(jobs, healthy, forced, k, base, period, q):
    """Try every choice of k distinct wafers/chambers and outward ranks."""

    def visit(in_rank, used_jobs, used_chambers, used_out):
        if in_rank < 0:
            return set(forced) <= used_jobs
        for j in jobs:
            if j.wafer in used_jobs:
                continue
            for chamber, duration in healthy[j.wafer]:
                if chamber in used_chambers:
                    continue
                for out_rank in range(k):
                    if (
                        out_rank not in used_out
                        and base + duration + j.residence - (in_rank + out_rank) * period >= q
                        and visit(
                            in_rank - 1,
                            used_jobs | {j.wafer},
                            used_chambers | {chamber},
                            used_out | {out_rank},
                        )
                    ):
                        return True
        return False

    return visit(k - 1, set(), set(), set())


def rank_bound(p, domain):
    jobs, pick, place, d = domain
    pack = last_load_bound(p, domain)
    if not pack or not 1 <= pack["min_pending"] <= 4 or len(jobs) > 14:
        return None
    last = next(j for j in jobs if j.wafer == pack["wafer"])
    others = [j for j in jobs if j != last]
    if any(j.residence is None for j in others):
        return None
    s = pick + place + 2 * d
    healthy = {j.wafer: [(c, t) for c, t in j.choices if c != p.failed_chamber] for j in others}
    first = min(max(j.ready, 0 if j.source == p.snapshot["robot"]["position"] else d) for j in jobs)
    maximum = len({c for options in healthy.values() for c, _ in options})
    base = last.due - 2 * pick - 2 * d - place
    split = pack["split_tick"]
    upper = split
    branches = []
    for k in range(pack["min_pending"], min(maximum, len(others)) + 1):
        rank = 2 * len(others) - k
        slack = last.due - pick - first - rank * s
        forced = []
        for j in others:
            # A completed pair at ranks u<v needs a window intersecting
            # (v-u)*s + [0,slack]. Place-completion shift is pick+d+place.
            if not any(
                max(dist * s, pick + d + place + t)
                <= min(dist * s + slack, d + place + t + j.residence)
                for c, t in healthy[j.wafer]
                for dist in range(1, rank)
            ):
                forced.append(j.wafer)
        windows = sorted(
            (
                t + j.residence
                for j in others
                for t in [max((v for _, v in healthy[j.wafer]), default=-(10**12))]
            ),
            reverse=True,
        )
        average_cap = base + sum(windows[:k]) // k - (k - 1) * s
        record = dict(
            pending=k,
            prefix_slots=rank,
            slack_tick=slack,
            forced_pending=forced,
            average_upper=average_cap,
        )
        branches.append(record)
        if slack < 0 or len(forced) > k or any(not v for v in healthy.values()):
            record["excluded"] = True
            continue
        if k == 1:
            candidates = [
                t + j.residence
                for j in others
                if not forced or j.wafer in forced
                for _, t in healthy[j.wafer]
            ]
            cap = base + max(candidates)
        elif k == 2:
            # Distinct jobs/chambers. The latest-loaded job has inward rank zero.
            cap = None
            for j, h in permutations(others, 2):
                if not set(forced) <= {j.wafer, h.wafer}:
                    continue
                for c, t in healthy[j.wafer]:
                    for b, v in healthy[h.wafer]:
                        if c == b:
                            continue
                        for first_out in (0, 1):
                            candidate = base + min(
                                t + j.residence - first_out * s,
                                v + h.residence - (2 - first_out) * s,
                            )
                            cap = candidate if cap is None else max(cap, candidate)
            if cap is None:
                record["excluded"] = True
                continue
        elif k <= 4 and average_cap > split:
            # The late branch only matters strictly above split.
            lo, hi = split, average_cap
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if compatible_slots(others, healthy, forced, k, base, s, mid):
                    lo = mid
                else:
                    hi = mid - 1
            cap = lo
        else:
            cap = average_cap
        record["upper_tick"] = cap
        upper = max(upper, cap)
    return dict(
        kind="terminal_rank_bound",
        wafer=last.wafer,
        split_tick=split,
        upper_tick=min(upper, pack["upper_tick"]),
        branches=branches,
    )


def solve_rank(
    p,
    domain,
    rank,
    upper,
    lower,
    deadline,
    *,
    last=None,
    pending_only=None,
    fixed=False,
    minimize=False,
    artifact=None,
):
    """All complete orders with their final source pickup at rank, above lower (inclusive)."""
    jobs, pick, place, d = domain
    s = pick + place + 2 * d
    total = 2 * len(jobs)
    initial = p.snapshot["robot"]["position"]
    max_due = max(j.due for j in jobs if last is None or j.wafer == last)
    # After the final source pick only its placement can hold up repair. With finite
    # inbound holds and terminal residence, all subsequent releases are bounded.
    horizon = max(
        j.due + j.hold_in + max(t for _, t in j.choices) + j.residence + pick + d + place
        for j in jobs
    )
    first = min(max(j.ready, 0 if j.source == initial else d) for j in jobs)
    slack = max_due - pick - rank * s - first
    meta = dict(rank=rank, last=last, lower_tick=lower, cap_tick=upper, fixed=fixed)
    if slack < 0 or lower > upper:
        return None, dict(**meta, status="INFEASIBLE", reason="rank_time_window")
    model = cp_model.CpModel()
    q = model.new_int_var(upper if fixed else lower, upper, "repair")
    a = [model.new_int_var(0, horizon, f"pick{i}") for i in range(total)]
    b = [model.new_int_var(0, horizon, f"place{i}") for i in range(total)]
    for i in range(total):
        model.add(b[i] >= a[i] + pick + d)
        if i:
            model.add(a[i] >= b[i - 1] + place + d)
        if i >= rank + 1:
            model.add(b[i] == a[i] + pick + d)
    model.add(a[0] >= first)
    model.add(a[rank] <= max_due - pick)
    slots = [[] for _ in a]
    occupy = {}
    flags = []
    for j in jobs:
        if perf_counter() >= deadline:
            return None, dict(**meta, status="UNKNOWN", reason="encoding_budget")
        opts = []
        for c, t in j.choices:
            if last and c == p.failed_chamber and j.wafer != last:
                # This specialization is only called above the proved late split.
                continue
            for u in range(rank + 1):
                if last and (j.wafer == last) != (u == rank):
                    continue
                min_a = max(first + u * s, j.ready, 0 if j.source == initial else d)
                if min_a + pick > j.due:
                    continue
                if (
                    u < rank
                    and c == p.failed_chamber
                    and max_due - pick - (rank - u) * s + pick + d < lower
                ):
                    continue
                for v in range(u + 1, total):
                    if v == rank:
                        continue
                    if (
                        pending_only
                        and j.wafer != last
                        and v > rank
                        and (j.wafer, c) not in pending_only
                    ):
                        continue
                    gap = (v - u) * s
                    if gap > d + place + t + j.residence:
                        continue
                    if v < rank and gap + slack < pick + d + place + t:
                        continue
                    lit = model.new_bool_var(f"{j.wafer}_{c}_{u}_{v}")
                    opts.append(lit)
                    slots[u].append(lit)
                    slots[v].append(lit)
                    for ix in range(u, v):
                        occupy.setdefault((c, ix), []).append(lit)
                    flags.append((lit, j, c, t, u, v))
                    model.add(a[u] >= min_a).only_enforce_if(lit)
                    model.add(a[u] + pick <= j.due).only_enforce_if(lit)
                    model.add(b[u] + place <= a[u] + pick + j.hold_in).only_enforce_if(lit)
                    model.add(a[v] >= b[u] + place + t).only_enforce_if(lit)
                    model.add(a[v] + pick <= b[u] + place + t + j.residence).only_enforce_if(lit)
                    model.add(b[v] == a[v] + pick + d).only_enforce_if(lit)
                    if j.hold_out is not None and d + place > j.hold_out:
                        model.add(lit == 0)
                    if c == p.failed_chamber:
                        model.add(b[u] >= q).only_enforce_if(lit)
        model.add_exactly_one(opts)
    for row in slots:
        model.add_exactly_one(row)
    for row in occupy.values():
        model.add_at_most_one(row)
    if minimize:
        if not fixed:
            raise ValueError("Makespan needs fixed repair")
        model.minimize(b[-1] + place)
    elif not fixed:
        model.maximize(q)
    if artifact is not None:
        import gzip
        import hashlib

        raw = model.proto.SerializeToString()
        artifact.write_bytes(gzip.compress(raw, mtime=0))
        meta.update(model=artifact.name, model_sha256=hashlib.sha256(raw).hexdigest())
    cp = cp_model.CpSolver()
    cp.parameters.num_search_workers = 1
    cp.parameters.random_seed = 0
    cp.parameters.max_time_in_seconds = max(0, deadline - perf_counter())
    status = cp.solve(model)
    if status == cp_model.MODEL_INVALID:
        raise ValueError(model.validate())
    meta.update(status=cp.status_name(status), branches=cp.num_branches, seconds=cp.wall_time)
    if artifact is not None:
        meta["response_stats"] = cp.response_stats()
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return None, meta
    transfers = []
    processes = []
    for flag, j, c, t, u, v in flags:
        if not cp.boolean_value(flag):
            continue
        for ix, src, dst, stage in ((u, j.source, c, j.stage), (v, c, "OUT", j.stage + 1)):
            start = cp.value(a[ix])
            put = cp.value(b[ix])
            transfers.append(
                dict(
                    wafer_id=j.wafer,
                    stage=stage,
                    source=src,
                    destination=dst,
                    initially_carried=False,
                    pick_start=start,
                    pick_end=start + pick,
                    place_start=put,
                    place_end=put + place,
                )
            )
        start = cp.value(b[u]) + place
        processes.append(
            dict(wafer_id=j.wafer, stage=j.stage, chamber=c, start=start, end=start + t)
        )
    transfers.sort(key=lambda row: row["pick_start"])
    schedule = dict(
        ticks_per_second=p.scale,
        transfers=transfers,
        processes=processes,
        makespan_tick=transfers[-1]["place_end"],
    )
    meta["repair_tick"] = cp.value(q)
    if minimize:
        meta["makespan_lower_tick"] = int(cp.best_objective_bound)
    elif not fixed:
        meta["objective_upper"] = int(cp.best_objective_bound)
    return schedule, meta


def pending_pairs(p, domain, cert, q):
    jobs, P, L, d = domain
    last = next(j for j in jobs if j.wafer == cert["wafer"])
    others = [j for j in jobs if j != last]
    allowed = set()
    base = last.due - 2 * P - 2 * d - L
    period = P + L + 2 * d
    for j, h in permutations(others, 2):
        for c, t in j.choices:
            for b, v in h.choices:
                if p.failed_chamber in (c, b) or c == b:
                    continue
                for o in (0, 1):
                    if (
                        min(
                            base + t + j.residence - o * period,
                            base + v + h.residence - (2 - o) * period,
                        )
                        >= q
                    ):
                        allowed.update(((j.wafer, c), (h.wafer, b)))
    return allowed


def ranked_recovery(case, p, prefix, domain, route, deadline):
    jobs, P, L, d = domain
    if any(j.hold_in is None or j.residence is None or j.due is None for j in jobs):
        return None
    pack = last_load_bound(p, domain)
    if not pack or pack["upper_tick"] <= pack["split_tick"]:
        return None
    cert = rank_bound(p, domain)
    if cert is None:
        return None
    n = len(jobs)
    cap = min(cert["upper_tick"], route["upper_tick"]) if route else cert["upper_tick"]
    kset = [b["pending"] for b in cert["branches"] if b.get("upper_tick", -1) >= cap]
    paired_tail = cap > cert["split_tick"] and kset == [2]
    targets = {c for j in jobs for c, _ in j.choices}
    first = min(max(j.ready, 0 if j.source == p.snapshot["robot"]["position"] else d) for j in jobs)
    # k pending plus the last-source wafer need k+1 separate destinations.
    low = max(n - 1, 2 * (n - 1) - (len(targets) - 1))
    high = min(2 * n - 2, (max(j.due for j in jobs) - P - first) // (P + L + 2 * d))
    if not paired_tail and (pack["min_pending"] < 3 or high - low > 2):
        return None
    scale, offset = p.scale, prefix["offset"]
    trace = [dict(tool="rank_bound", **cert)]
    best = None
    qbest = -1

    def keep(plan, q):
        nonlocal best, qbest
        if plan and (q > qbest or (q == qbest and plan["makespan_tick"] < best["makespan_tick"])):
            best, qbest = plan, q

    def probe(rank, hi, lo, until, **kw):
        plan, row = solve_rank(p, domain, rank, hi, lo, until, **kw)
        trace.append(dict(tool="rank_query", **row))
        if plan:
            keep(plan, row["repair_tick"])
        return row

    # Include encoding/verification in the outer wall budget.
    start = perf_counter()
    remaining = max(0, deadline - start)
    until = deadline - min(0.15, remaining * 0.15)
    optimal_makespan = False
    if paired_tail:
        row = probe(
            2 * (n - 1) - 2,
            cap,
            cap,
            min(until, start + 0.65 * remaining),
            last=cert["wafer"],
            pending_only=pending_pairs(p, domain, cert, cap),
            fixed=True,
            minimize=True,
        )
        if best is not None:
            optimal_makespan = row["status"] == "OPTIMAL" or best[
                "makespan_tick"
            ] == cap + L + 3 * (P + L + 2 * d)
        elif row["status"] == "INFEASIBLE":
            cap -= 1
        # An unsuccessful cap query is not evidence against lower repair times.
        if best is None and until > perf_counter():
            from .terminal_exact import solve_terminal

            fallback = solve_terminal(case, p, prefix, domain, route, until)
            if fallback is not None:
                bound = offset + cap / scale
                old = fallback.get("finite_upper_seconds")
                fallback["finite_upper_seconds"] = bound if old is None else min(old, bound)
                if (
                    fallback.get("verification_valid")
                    and fallback.get("verified_feasible_lower_seconds")
                    == fallback["finite_upper_seconds"]
                ):
                    fallback.update(
                        status="FINITE",
                        latest_repair_delay_seconds=fallback["finite_upper_seconds"],
                    )
                fallback["trace"] = trace + fallback["trace"]
                return fallback
    else:
        # Search the denser prefix first. Remaining rank slices keep the global cap until closed.
        bounds = {r: cap for r in range(low, high + 1)}
        for r in reversed(bounds):
            now = perf_counter()
            if now >= until:
                break
            row = probe(r, cap, max(0, qbest), now + (until - now) / (r - low + 1))
            if row["status"] == "INFEASIBLE":
                bounds[r] = qbest - 1 if qbest >= 0 else -1
            elif "objective_upper" in row:
                bounds[r] = row["objective_upper"]
        cap = max(bounds.values(), default=-1)
        if best is not None and cap == qbest:
            optimal_makespan = True
            for r, bound in bounds.items():
                if bound < cap:
                    continue
                if perf_counter() >= until:
                    optimal_makespan = False
                    break
                row = probe(r, cap, cap, until, fixed=True, minimize=True)
                if row["status"] not in {"OPTIMAL", "INFEASIBLE"}:
                    optimal_makespan = False
    out = dict(
        status="UNKNOWN" if cap >= 0 else "INFEASIBLE_AT_ZERO",
        trace=trace,
        makespan_optimal=optimal_makespan,
        finite_upper_seconds=offset + cap / scale if cap >= 0 else None,
    )
    if best is not None:
        delay = qbest / scale
        check = replay_recovery(p, delay, best)
        if not check["valid"]:
            raise RuntimeError(check["errors"])
        verified = dict(
            schedule=best, verification={k: v for k, v in check.items() if k != "trace"}
        )
        out.update(
            best=verified,
            verification_valid=True,
            makespan_seconds=offset + best["makespan_tick"] / scale,
            verified_feasible_lower_seconds=offset + delay,
            witness_repair_delay_seconds=offset + delay,
        )
        if qbest == cap:
            out.update(status="FINITE", latest_repair_delay_seconds=offset + delay)
        replay_incident(case, prefix, out, verified)
    return out
