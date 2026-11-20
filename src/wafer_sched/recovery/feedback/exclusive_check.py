"""Post-study arithmetic audit; never imported by a benchmark solver."""

import json
from .diagnosis import ROOT
from ..continuation import Continuation
from ..short_budget import PreparedIncident
from ..terminal_exact import terminal_domain
from ..evidence_study import save


def certificate(p):
    jobs, P, L, d = terminal_domain(p)
    rows = []
    for c in sorted({c for j in jobs for c, _ in j.choices}):
        group = [j for j in jobs if {a for a, _ in j.choices} == {c}]
        if len(group) < 2 or any(j.due is None for j in group):
            continue
        costs = {j.wafer: 2 * (P + L) + 3 * d + j.choices[0][1] for j in group}
        first = min(
            max(j.ready, 0 if j.source == p.snapshot["robot"]["position"] else d) for j in group
        )
        hypotheses = [
            dict(
                last=j.wafer,
                earliest_pick=first + sum(costs.values()) - costs[j.wafer],
                latest_pick=j.due - P,
            )
            for j in group
        ]
        excess = min(h["earliest_pick"] - h["latest_pick"] for h in hypotheses)
        if excess > 0:
            rows.append(
                dict(
                    chamber=c,
                    min_excess_tick=excess,
                    ticks_per_second=p.scale,
                    earliest_first=first,
                    lower_cycle_ticks=costs,
                    last_cases=hypotheses,
                )
            )
    return rows


if __name__ == "__main__":
    out = {}
    for path in sorted((ROOT / "holdout" / "inputs").glob("*.json")):
        case = Continuation.from_dict(json.loads(path.read_bytes()))
        p, _ = PreparedIncident(**vars(case)).prepare()
        found = certificate(p)
        if found:
            timed = json.loads(
                (ROOT / "holdout" / "b30" / path.stem / "0-agent.json").read_bytes()
            )["metrics"]
            assert not timed["verified"] and timed["status"] in {"INFEASIBLE_AT_ZERO", "UNKNOWN"}
            out[path.stem] = dict(timed_agent_status=timed["status"], certificates=found)
    save(ROOT / "exclusive-audit.json", out)
