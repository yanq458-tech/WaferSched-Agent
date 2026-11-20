"""Exhaustive slot cover for tight terminal ranks. Time constraints are difference inequalities."""

from collections import deque
from time import perf_counter


def earliest(edges, seed):
    """Least solution above the supplied seed of t[v] >= t[u]+w, with origin fixed."""
    times = list(seed)
    size = len(times)
    queue = deque(range(size))
    queued = [True] * size
    depth = [0] * size
    while queue:
        u = queue.popleft()
        queued[u] = False
        for v, w in edges[u]:
            t = times[u] + w
            if t <= times[v]:
                continue
            if not v or depth[u] + 1 >= size:
                return None
            times[v] = t
            depth[v] = depth[u] + 1
            if not queued[v]:
                queued[v] = True
                queue.append(v)
    return times


def cover_rank(p, domain, rank, cap, lower, deadline):
    jobs, P, L, d = domain
    n = len(jobs)
    m = 2 * n
    s = P + L + 2 * d
    initial = p.snapshot["robot"]["position"]
    first = min(max(j.ready, 0 if j.source == initial else d) for j in jobs)
    latest = max(j.due for j in jobs) - P
    slack = latest - first - rank * s
    rows = []
    columns = [0] * (m + n)
    by_chamber = {}
    # Each row consumes a job, two robot slots and one chamber between its slots.
    for i, j in enumerate(jobs):
        for c, t in j.choices:
            if d + L > j.hold_in or j.hold_out is not None and d + L > j.hold_out:
                continue
            for u in range(rank + 1):
                amin = max(j.ready, first + u * s, 0 if j.source == initial else d)
                amax = min(j.due - P, latest - (rank - u) * s)
                if amin > amax:
                    continue
                bmax = amax + P + j.hold_in - L
                if u < rank:
                    bmax = min(bmax, latest - (rank - u) * s + P + d)
                if c == p.failed_chamber and bmax < lower:
                    continue
                for v in range(u + 1, m):
                    gap = (v - u) * s
                    if v == rank or gap > d + L + t + j.residence:
                        continue
                    if v < rank and gap + slack < P + d + L + t:
                        continue
                    bit = 1 << len(rows)
                    cols = (u, v, m + i)
                    rows.append((j, c, t, u, v, cols, bmax))
                    for col in cols:
                        columns[col] |= bit
                    for slot in range(u, v):
                        by_chamber[c, slot] = by_chamber.get((c, slot), 0) | bit
    incompatible = []
    for _, c, _, u, v, cols, _ in rows:
        mask = 0
        for col in cols:
            mask |= columns[col]
        for slot in range(u, v):
            mask |= by_chamber[c, slot]
        incompatible.append(mask)
    best = None
    bestq = lower - 1
    incumbent_end = None
    gates_by_limit = sorted(
        (row[-1], 1 << k) for k, row in enumerate(rows) if row[1] == p.failed_chamber
    )
    blocked = 0
    threshold_index = 0
    horizon = max(j.due + j.hold_in + max(t for _, t in j.choices) + j.residence + s for j in jobs)
    path = []
    nodes = 0
    leaves = 0
    finished = True
    size = 2 * m + 1
    base = [[] for _ in range(size)]
    for i in range(m):
        a = 1 + 2 * i
        base[a].append((a + 1, P + d))
        if i + 1 < m:
            base[a + 1].append((a + 2, L + d))

    def assess():
        nonlocal bestq, best, incumbent_end, leaves, threshold_index, blocked
        leaves += 1
        edges = [list(x) for x in base]
        gates = []
        for k in path:
            j, c, t, u, v, _, _ = rows[k]
            a, b = 1 + 2 * u, 2 + 2 * u
            h = 1 + 2 * v
            edges[0].append((a, max(j.ready, 0 if j.source == initial else d)))
            edges[a].append((0, P - j.due))
            edges[b].append((a, L - P - j.hold_in))
            edges[b].append((h, L + t))
            edges[h].append((b, P - L - t - j.residence))
            edges[h + 1].append((h, -P - d))
            if c == p.failed_chamber:
                gates.append(b)
        # Reversed edges with negated clocks bound how late each repair-gated placement
        # can be. Zero seed would impose artificial deadlines: use a proved horizon.

        rev = [[] for _ in edges]
        for u, neighbors in enumerate(edges):
            for v, w in neighbors:
                rev[v].append((u, w))
        late = earliest(rev, [0] + [-horizon] * (size - 1))
        if late is None:
            return
        q = min([cap] + [-late[g] for g in gates])
        if q < max(lower, bestq):
            return
        seed = [0] * size
        for g in gates:
            seed[g] = q
        actual = earliest(edges, seed)
        if actual is None:
            return
        end = actual[-1] + L
        if q == bestq and incumbent_end is not None and end >= incumbent_end:
            return
        bestq, incumbent_end = q, end
        best = (path.copy(), actual)
        while threshold_index < len(gates_by_limit) and gates_by_limit[threshold_index][0] < q:
            blocked |= gates_by_limit[threshold_index][1]
            threshold_index += 1

    def search(active, free):
        nonlocal nodes, finished
        nodes += 1
        if nodes % 32 == 0 and perf_counter() >= deadline:
            finished = False
        if not finished:
            return
        if not free:
            assess()
            return
        active &= ~blocked
        bits = free
        count = len(rows) + 1
        choices = 0
        while bits:
            one = bits & -bits
            bits ^= one
            sel = columns[one.bit_length() - 1] & active
            total = sel.bit_count()
            if not total:
                return
            if total < count:
                count, choices = total, sel
        while choices and finished:
            one = choices & -choices
            choices ^= one
            k = one.bit_length() - 1
            j, c, t, u, v, cols, limit = rows[k]
            if c == p.failed_chamber and limit < bestq:
                continue
            path.append(k)
            search(active & ~incompatible[k], free ^ ((1 << u) | (1 << v) | (1 << cols[2])))
            path.pop()

    search((1 << len(rows)) - 1, (1 << len(columns)) - 1)
    meta = dict(
        rank=rank,
        lower_tick=lower,
        cap_tick=cap,
        cover_nodes=nodes,
        complete_orders=leaves,
        status=("OPTIMAL" if best else "INFEASIBLE")
        if finished
        else ("FEASIBLE" if best else "UNKNOWN"),
    )
    if not best:
        return None, meta
    selected, times = best
    transfers = []
    processes = []
    for k in selected:
        j, c, t, u, v, _, _ = rows[k]
        for ix, src, dst, stage in ((u, j.source, c, j.stage), (v, c, "OUT", j.stage + 1)):
            a, b = times[1 + 2 * ix : 3 + 2 * ix]
            transfers.append(
                dict(
                    wafer_id=j.wafer,
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
        start = times[2 + 2 * u] + L
        processes.append(
            dict(wafer_id=j.wafer, stage=j.stage, chamber=c, start=start, end=start + t)
        )
    transfers.sort(key=lambda r: r["pick_start"])
    meta.update(repair_tick=bestq, objective_upper=bestq if finished else cap)
    return dict(
        transfers=transfers,
        processes=processes,
        ticks_per_second=p.scale,
        makespan_tick=incumbent_end,
    ), meta
