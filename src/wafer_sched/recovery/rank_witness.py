"""Construct a boundary witness on a regular transfer grid; failure carries no proof."""

from itertools import permutations
from random import Random
from time import perf_counter


def grid_cover(jobs, times, p, P, L, d, deadline):
    """Cover every transfer slot and wafer once, with disjoint chamber occupancies."""
    m = len(times)
    rows = []
    columns = [[] for _ in range(m + len(jobs))]
    initial = p.snapshot["robot"]["position"]
    for i, job in enumerate(jobs):
        if job.hold_in < d + L or (job.hold_out is not None and job.hold_out < d + L):
            return None
        for c, t in job.choices:
            if c == p.failed_chamber:
                continue
            for u, start in enumerate(times):
                if start < max(job.ready, 0 if job.source == initial else d) or start + P > job.due:
                    continue
                ready = start + P + d + L + t
                for v in range(u + 1, m):
                    if not ready <= times[v] <= ready + job.residence - P:
                        continue
                    mask = (1 << u) | (1 << v) | (1 << (m + i))
                    interval = (1 << v) - (1 << u)
                    k = len(rows)
                    rows.append((mask, interval, c, job, u, v, t))
                    for col in (u, v, m + i):
                        columns[col].append(k)
    used = {}
    path = []
    visits = 0

    def visit(open_cols):
        nonlocal visits
        if not open_cols:
            return list(path)
        visits += 1
        if visits % 64 == 0 and perf_counter() >= deadline:
            return None
        best = None
        bits = open_cols
        while bits:
            bit = bits & -bits
            bits ^= bit
            candidates = []
            for k in columns[bit.bit_length() - 1]:
                mask, interval, c, *_ = rows[k]
                if mask & open_cols == mask and not used.get(c, 0) & interval:
                    candidates.append(k)
            if not candidates:
                return None
            if best is None or len(candidates) < len(best):
                best = candidates
        for k in best:
            mask, interval, c, *_ = rows[k]
            used[c] = used.get(c, 0) | interval
            path.append(rows[k])
            result = visit(open_cols ^ mask)
            if result is not None:
                return result
            path.pop()
            used[c] ^= interval
            if perf_counter() >= deadline:
                break
        return None

    return visit((1 << len(columns)) - 1)


def construct(p, domain, cert, cap, allowed, deadline):
    jobs, P, L, d = domain
    s = P + L + 2 * d
    last = next(j for j in jobs if j.wafer == cert["wafer"])
    rank = 2 * len(jobs) - 4
    m = rank - 2
    if m < 2:
        return None
    options = [(j, c, t) for j in jobs for c, t in j.choices if (j.wafer, c) in allowed]
    A = last.due - P
    latest = A - 2 * s
    b_last = max(cap, A + P + d)
    put_out = b_last + L + d
    initial = p.snapshot["robot"]["position"]

    def legal(j, u, b, v, t):
        return (
            u >= max(j.ready, 0 if j.source == initial else d)
            and u + P <= j.due
            and b + L - u - P <= j.hold_in
            and b + L + t <= v <= b + L + t + j.residence - P
            and (j.hold_out is None or j.hold_out >= d + L)
        )

    def emit(j, c, t, u, b, v):
        return [
            (j.wafer, j.stage, j.source, c, u, b),
            (j.wafer, j.stage + 1, c, "OUT", v, v + P + d),
        ], dict(wafer_id=j.wafer, stage=j.stage, chamber=c, start=b + L, end=b + L + t)

    tails = []
    for x, y in permutations(options, 2):
        if x[0] == y[0] or x[1] == y[1]:
            continue
        for order in (0, 1):
            pieces = []
            for (j, c, t), u, v in (
                (x, latest, put_out + order * s),
                (y, A - s, put_out + (1 - order) * s),
            ):
                b = u + P + d
                if legal(j, u, b, v, t):
                    pieces.append(emit(j, c, t, u, b, v))
            for c, t in last.choices:
                v = put_out + 2 * s
                if c == p.failed_chamber and len(pieces) == 2 and legal(last, A, b_last, v, t):
                    prefix = [j for j in jobs if j not in (last, x[0], y[0])]
                    tails.append((prefix, [*pieces, emit(last, c, t, A, b_last, v)]))
    rng = Random(0)
    grids = 0
    for attempt in range(100):
        for prefix, tail in tails:
            if perf_counter() >= deadline:
                return None
            first = min(max(j.ready, d if j.source != initial else 0) for j in prefix)
            slack = latest - m * s - first
            if slack < 0:
                continue
            # Regular clocks first, then redistribute idle ticks deterministically.
            if attempt < 3:
                phases = [
                    i * (slack if attempt == 0 else slack // 2 if attempt == 1 else 0) // (m - 1)
                    for i in range(m)
                ]
            else:
                phases = sorted(rng.randrange(slack + 1) for _ in range(m))
            times = [first + i * s + phases[i] for i in range(m)]
            grids += 1
            cover = grid_cover(prefix, times, p, P, L, d, deadline)
            if cover is None:
                continue
            pieces = tail + [
                emit(j, c, t, times[u], times[u] + P + d, times[v]) for _, _, c, j, u, v, t in cover
            ]
            transfers = []
            for actions, _ in pieces:
                for wid, stage, src, dst, a, b in actions:
                    transfers.append(
                        dict(
                            wafer_id=wid,
                            stage=stage,
                            source=src,
                            destination=dst,
                            initially_carried=False,
                            pick_start=a,
                            pick_end=a + P,
                            place_start=b,
                            place_end=b + L,
                        )
                    )
            transfers.sort(key=lambda row: row["pick_start"])
            plan = dict(
                ticks_per_second=p.scale,
                transfers=transfers,
                processes=[proc for _, proc in pieces],
                makespan_tick=transfers[-1]["place_end"],
            )
            return plan, grids
    return None
