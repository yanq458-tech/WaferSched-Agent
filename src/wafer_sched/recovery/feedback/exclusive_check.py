"""Arithmetic conflict for terminal jobs whose sole eligible chamber is shared."""

import json
from .diagnosis import ROOT
from ..continuation import Continuation
from ..short_budget import PreparedIncident
from ..terminal_exact import terminal_domain
from ..evidence_study import save


def certificate(p, domain=None):
    domain = terminal_domain(p) if domain is None else domain
    if domain is None:
        return []
    jobs, P, L, d = domain
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
                    kind="exclusive_terminal_deadlines",
                    chamber=c,
                    min_excess_tick=excess,
                    ticks_per_second=p.scale,
                    earliest_first=first,
                    lower_cycle_ticks=costs,
                    last_cases=hypotheses,
                )
            )
    return rows


def verify(p, record):
    """Independently check the claimed group, each candidate last pickup and strict excess."""
    domain = terminal_domain(p)
    if not domain or record.get("kind") != "exclusive_terminal_deadlines":
        return False
    jobs, pick, place, travel = domain
    chamber = record.get("chamber")
    group = [j for j in jobs if len(j.choices) == 1 and j.choices[0][0] == chamber]
    if len(group) < 2 or any(j.due is None for j in group):
        return False
    origin = p.snapshot["robot"]["position"]
    start = min(max(j.ready, 0 if origin == j.source else travel) for j in group)
    costs = {j.wafer: pick + travel + place + j.choices[0][1] + pick + travel + place + travel
             for j in group}
    expected = []
    for last in group:
        earliest = start + sum(cost for wafer, cost in costs.items() if wafer != last.wafer)
        expected.append(dict(last=last.wafer, earliest_pick=earliest, latest_pick=last.due - pick))
    margin = min(h["earliest_pick"] - h["latest_pick"] for h in expected)
    return (margin > 0 and record.get("min_excess_tick") == margin
            and record.get("earliest_first") == start and record.get("lower_cycle_ticks") == costs
            and record.get("ticks_per_second") == p.scale and record.get("last_cases") == expected)


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
