"""Sufficient terminal schedules on sampled clocks; no exclusion on failed construction."""

from bisect import bisect_left, bisect_right
from random import Random
from time import perf_counter


def cover(p, jobs, clock, P, L, d, q, deadline, seed):
    rows = []
    m = len(clock)
    initial = p.snapshot["robot"]["position"]
    for k, j in enumerate(jobs):
        if min(x for x in (j.hold_in, j.hold_out, d + L) if x is not None) < d + L:
            return None
        for c, t in j.choices:
            for u, a in enumerate(clock):
                b = a + P + d
                if (
                    a < max(j.ready, 0 if j.source == initial else d)
                    or a + P > j.due
                    or (c == p.failed_chamber and b < q)
                ):
                    continue
                ready = b + L + t
                for v in range(
                    bisect_left(clock, ready, u + 1), bisect_right(clock, ready + j.residence - P)
                ):
                    rows.append((u, v, k, c, t))
    Random(seed).shuffle(rows)
    columns = [0] * (m + len(jobs))
    chamber = {}
    for ix, (u, v, k, c, t) in enumerate(rows):
        bit = 1 << ix
        for col in (u, v, k + m):
            columns[col] |= bit
        for z in range(u, v):
            chamber[c, z] = chamber.get((c, z), 0) | bit
    block = []
    used = []
    for u, v, k, c, t in rows:
        conflicts = columns[u] | columns[v] | columns[k + m]
        for z in range(u, v):
            conflicts |= chamber[c, z]
        block.append(conflicts)
        used.append((1 << u) | (1 << v) | (1 << (k + m)))
    path = []

    def visit(active, free):
        if not free:
            return True
        if perf_counter() >= deadline:
            return False
        bits = free
        best_count = len(rows) + 1
        opts = 0
        while bits:
            col = bits & -bits
            bits ^= col
            available = active & columns[col.bit_length() - 1]
            count = available.bit_count()
            if not count:
                return False
            if count < best_count:
                best_count, opts = count, available
        while opts and perf_counter() < deadline:
            flag = opts & -opts
            opts ^= flag
            ix = flag.bit_length() - 1
            path.append(ix)
            if visit(active & ~block[ix], free ^ used[ix]):
                return True
            path.pop()
        return False

    if not visit((1 << len(rows)) - 1, (1 << len(columns)) - 1):
        return None
    return [
        (jobs[k], c, t, clock[u], clock[u] + P + d, clock[v])
        for u, v, k, c, t in (rows[ix] for ix in path)
    ]


def construct(p, domain, q, deadline):
    jobs, P, L, d = domain
    s = P + L + 2 * d
    mandatory = [j for j in jobs if all(c == p.failed_chamber for c, _ in j.choices)]
    # A delayed final failed load permits intentional holding during repair.
    last = min(mandatory, key=lambda j: j.due) if q and mandatory else None
    group = [j for j in jobs if j != last]
    m = 2 * len(group)
    first = min(
        max(j.ready, 0 if j.source == p.snapshot["robot"]["position"] else d) for j in group
    )
    slack = (
        last.due - P - m * s - first if last else max(j.due for j in jobs) - first - (m - 4) * s - P
    )
    rng = Random(571)
    attempt = 0
    while perf_counter() < deadline:
        span = max(0, slack)
        if attempt == 0:
            span = 0
        elif attempt == 2:
            span //= 2
        if attempt < 3:
            idle = [i * span // max(1, m - 1) for i in range(m)]
        elif attempt % 3:
            jumps = sorted(rng.sample(range(1, m), min(m - 1, rng.randint(1, 5))))
            levels = sorted(rng.randrange(span + 1) for _ in jumps[:-1]) + [span]
            idle = [
                next((v for k, v in reversed(list(zip(jumps, levels))) if i >= k), 0)
                for i in range(m)
            ]
        else:
            idle = sorted(rng.randrange(span + 1) for _ in range(m))
        clock = [first + i * s + v for i, v in enumerate(idle)]
        attempt += 1
        parts = cover(p, group, clock, P, L, d, q, min(deadline, perf_counter() + 0.12), attempt)
        if parts is None:
            continue
        if last:
            a = max(last.ready, clock[-1] + s, q + L - last.hold_in - P)
            b = max(q, a + P + d)
            c, t = last.choices[0]
            if (
                a + P > last.due
                or b + L > a + P + last.hold_in
                or last.residence < P
                or (last.hold_out is not None and last.hold_out < d + L)
            ):
                continue
            parts.append((last, c, t, a, b, b + L + t))
        transfers = []
        processes = []
        for j, c, t, a, b, v in parts:
            for src, dst, stage, start, put in (
                (j.source, c, j.stage, a, b),
                (c, "OUT", j.stage + 1, v, v + P + d),
            ):
                transfers.append(
                    dict(
                        wafer_id=j.wafer,
                        stage=stage,
                        source=src,
                        destination=dst,
                        initially_carried=False,
                        pick_start=start,
                        pick_end=start + P,
                        place_start=put,
                        place_end=put + L,
                    )
                )
            processes.append(
                dict(wafer_id=j.wafer, stage=j.stage, chamber=c, start=b + L, end=b + L + t)
            )
        transfers.sort(key=lambda x: x["pick_start"])
        return dict(
            transfers=transfers,
            processes=processes,
            ticks_per_second=p.scale,
            makespan_tick=transfers[-1]["place_end"],
        ), attempt
    return None, attempt
