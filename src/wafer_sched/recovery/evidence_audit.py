"""Independently re-open serialized schedules/certificates and score paired comparisons."""

from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median
import argparse

from .conflict_evidence import verify_bound
from .continuation import Continuation, delta
from .dispatch import replay_incident
from .evidence_study import ROOT, save, METHODS
from .replay import replay_recovery


def audit(root, label):
    folder = root / label
    groups = defaultdict(dict)
    proofs = Counter()
    raw_proofs = defaultdict(set)
    witness_delays = defaultdict(list)
    certified_uppers = defaultdict(list)
    witness_count = 0
    for path in sorted((folder / "runs").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf8"))
        m = data["metrics"]
        case = Continuation.from_dict(
            json.loads((root / "inputs" / (m["case"] + ".json")).read_text(encoding="utf8"))
        )
        p, prefix = case.prepare()
        if data.get("certificate"):
            assert verify_bound(p, data["certificate"]), path
            proofs[data["certificate"]["kind"]] += 1
            certified_uppers[m["case"]].append(
                prefix["offset"] + data["certificate"]["upper_tick"] / p.scale
            )
        if data.get("schedule"):
            r = data["witness_repair"]
            plan = data["schedule"]
            suffix = replay_recovery(p, max(0, delta(r, prefix["offset"])), plan)
            assert suffix["valid"], path
            assert (
                abs(data["raw_makespan"] - prefix["offset"] - plan["makespan_tick"] / p.scale)
                < 1e-8
            )
            witness_delays[m["case"]].append(r)
            out = dict(witness_repair_delay_seconds=r, makespan_seconds=data["raw_makespan"])
            replay_incident(case, prefix, out, {"verification": suffix})
            witness_count += 1
        if m["raw_status"] in ("FINITE", "UNBOUNDED", "INFEASIBLE_AT_ZERO"):
            raw_proofs[m["case"]].add(
                (m["raw_status"], data["witness_repair"] if m["raw_status"] == "FINITE" else None)
            )
        groups[m["case"], m["repeat"]][m["method"]] = m
    if not groups:
        raise ValueError("No saved runs")
    for name in {k[0] for k in groups}:
        assert len(raw_proofs[name]) <= 1, (name, raw_proofs[name])
        if witness_delays[name]:
            assert ("INFEASIBLE_AT_ZERO", None) not in raw_proofs[name]
            for upper in certified_uppers[name]:
                assert max(witness_delays[name]) <= upper
        if certified_uppers[name]:
            assert ("UNBOUNDED", None) not in raw_proofs[name]
    pairs = {}
    for baseline in ("binary", "direct", "plain_policy"):
        outcomes = Counter()
        for runs in groups.values():
            assert set(runs) == set(METHODS)
            a, b = runs["graph_policy"], runs[baseline]

            def success(r):
                return r["status"] in ("FINITE", "UNBOUNDED", "INFEASIBLE_AT_ZERO")

            if success(a) and success(b):
                assert (a["status"], a["rho"]) == (b["status"], b["rho"])
                if a["makespan_optimal"] and b["makespan_optimal"] and a["rho"] is not None:
                    assert a["makespan"] == b["makespan"]
                outcomes["both_proved"] += 1
            elif success(a):
                outcomes["graph_only_proved"] += 1
            elif success(b):
                outcomes["baseline_only_proved"] += 1
            else:
                outcomes["neither_proved"] += 1
        pairs[baseline] = dict(outcomes)
    summary = {}
    for method in METHODS:
        rows = [v[method] for v in groups.values()]
        summary[method] = {}
        for family in ["all", *sorted({r["family"] for r in rows})]:
            items = [r for r in rows if family == "all" or r["family"] == family]
            gaps = [r["gap"] for r in items if r["gap"] is not None]
            first = [
                r["first_suffix_witness_seconds"]
                for r in items
                if r["first_suffix_witness_seconds"] is not None
            ]
            summary[method][family] = dict(
                runs=len(items),
                statuses=dict(Counter(r["status"] for r in items)),
                median_wall=median(r["wall_seconds"] for r in items),
                first_witness_n=len(first),
                median_first_witness=median(first) if first else None,
                gap_n=len(gaps),
                median_gap=median(gaps) if gaps else None,
            )
    result = dict(
        pairs=len(groups),
        serialized_plans_replayed=witness_count,
        certificates_rechecked=dict(proofs),
        graph_vs=pairs,
        by_family=summary,
    )
    save(folder / "audit.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT)
    parser.add_argument("--label", default="benchmark")
    args = parser.parse_args()
    audit(args.out, args.label)
