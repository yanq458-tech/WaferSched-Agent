"""Audit the timed six-case retest and derive paired, historical and cumulative results."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from retest_six_recovery import ARCHIVE, CASES
from review_learned_recovery import classify, delta, endpoint, why
from review_value_agent import decisions
from wafer_sched.recovery import holdout, terminal_exact
from wafer_sched.recovery.conflict_evidence import verify_bound
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.evidence_study import save
from wafer_sched.recovery.feedback.audit import replay
from wafer_sched.recovery.feedback.learned_study import conflict_check, read


def endpoints(records):
    lows = [r["lower"] for r in records if r["lower"] is not None]
    caps = [r["upper"] for r in records if r["upper"] is not None]
    lo, hi = max(lows, default=None), min(caps, default=None)
    statuses = {r["status"] for r in records}
    assert lo is None or hi is None or lo <= hi
    assert "INFEASIBLE_AT_ZERO" not in statuses or lo is None
    status = ("INFEASIBLE_AT_ZERO" if "INFEASIBLE_AT_ZERO" in statuses else
              "FINITE" if lo is not None and lo == hi else "UNKNOWN")
    return dict(lower=lo, upper=hi, status=status)


def change(old, new):
    return dict(lower_gain=delta(new["lower"], old["lower"]),
                upper_gain=delta(old["upper"], new["upper"]),
                gap_reduction=delta(delta(old["upper"], old["lower"]),
                                    delta(new["upper"], new["lower"])))


def csv_out(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def audit_evidence(case, p, prefix, record, plans, certs):
    raw = record["raw"]
    plan = (raw.get("best") or {}).get("schedule")
    if plan:
        delay = raw["witness_repair_delay_seconds"]
        key = record["case"], delay, json.dumps(plan, sort_keys=True)
        if key not in plans:
            replay(case, plan, delay)
            plans.add(key)
        assert raw["verified_feasible_lower_seconds"] == delay
    else:
        assert raw.get("verified_feasible_lower_seconds") is None
    cert = raw["certificate"]
    key = record["case"], json.dumps(cert, sort_keys=True)
    if key not in certs:
        if "upper_tick" in cert:
            assert verify_bound(p, cert)
        else:
            assert conflict_check(p, cert)
        certs.add(key)
    hi = cert.get("upper_tick", -1)
    for event in raw["trace"]:
        tool = event["tool"]
        if tool == "terminal_last_load_bound":
            rebuilt = terminal_exact.last_load_bound(p, terminal_exact.terminal_domain(p))
            assert rebuilt == {k: v for k, v in event.items() if k != "tool"}
            hi = min(hi, event["upper_tick"])
        elif tool == "pilot_feedback":
            assert event["upper_tick"] <= hi
            hi = event["upper_tick"]
        elif tool == "prefix_capacity_relaxation":
            assert event["prior_upper"] == hi and event["upper_tick"] <= hi
            if event["status"] == "UNKNOWN":
                assert event["upper_tick"] == hi
            hi = event["upper_tick"]
        elif tool == "strengthened_fixed_repair" and event["status"] == "INFEASIBLE":
            hi = min(hi, event["repair_tick"] - 1)
    cap = prefix["offset"] + hi / p.scale if hi >= 0 else None
    assert raw.get("finite_upper_seconds") == cap
    assert record["late"] == (record["wall"] > record["budget"])
    assert record["status"] == ("UNKNOWN" if record["late"] else raw["status"])
    assert record["lower"] == (None if record["late"] else raw.get("verified_feasible_lower_seconds"))
    assert record["upper"] == (None if record["late"] else cap)
    if record["status"] == "FINITE":
        assert record["lower"] is not None and record["lower"] == cap


def review(out):
    if not __debug__:
        raise RuntimeError("Run the audit without -O")
    settings = read(out / "protocol.json")
    assert settings["frozen"] == read(ARCHIVE / "freeze.json")
    assert all(holdout.digest(ARCHIVE / f) == digest for f, digest in settings["frozen"].items())
    paired, historical, summary, choices = [], [], [], []
    plans, certs = set(), set()
    counts = Counter()
    assert len(list((out / "runs").glob("*/*/*.json"))) == len(CASES)*8
    for name in CASES:
        path = ARCHIVE / "inputs" / (name + ".json")
        assert holdout.digest(path) == settings["input_hashes"][name]
        case = Continuation.from_dict(read(path))
        p, prefix = case.prepare()
        prior, fresh = [], []
        for budget in (1, 30):
            for rep in (0, 1):
                batch = {}
                for arm in ("human", "value"):
                    suffix = Path("runs") / str(budget) / name / f"{rep}-{arm}.json"
                    r, old = read(out / suffix), read(ARCHIVE / suffix)
                    assert (r["case"], r["arm"], r["budget"], r["rep"]) == (name, arm, budget, rep)
                    first = settings["cases"][name]["first"]
                    assert r["order"] == (first[::-1] if rep else first)
                    assert r["core"] == settings["cases"][name]["core"] == old["core"]
                    audit_evidence(case, p, prefix, r, plans, certs)
                    counts["runs"] += 1
                    counts["late"] += r["late"]
                    counts["exact"] += r["status"] != "UNKNOWN"
                    counts["witness_records"] += bool((r["raw"].get("best") or {}).get("schedule"))
                    if arm == "value":
                        choices.extend(decisions(r))
                    prior.append(old)
                    fresh.append(r)
                    batch[arm] = r
                    historical.append(dict(case=name, budget=budget, repeat=rep, arm=arm,
                        previous=endpoint(old), current=endpoint(r), outcome=classify(old, r),
                        **change(old, r), wall=r["wall"], reason=why(r), log=suffix.as_posix()))
                h, a = batch["human"], batch["value"]
                paired.append(dict(case=name,budget=budget,repeat=rep,human=endpoint(h),agent=endpoint(a),
                    outcome=classify(h,a),**change(h,a),human_wall=h["wall"],agent_wall=a["wall"],
                    human_reason=why(h),agent_reason=why(a)))
        old_best, new_best, combined = endpoints(prior), endpoints(fresh), endpoints(prior+fresh)
        summary.append(dict(case=name, previous=endpoint(old_best), retest=endpoint(new_best),
                            retained=endpoint(combined), **change(old_best, combined)))
    csv_out(out / "paired.csv", paired)
    csv_out(out / "historical.csv", historical)
    csv_out(out / "retained.csv", summary)
    save(out / "decisions.json", choices)
    save(out / "audit.json", dict(**counts, distinct_replayed=len(plans),
         distinct_route_or_conflict_certificates=len(certs), decisions=len(choices),
         checked_run_endpoints=len(historical)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    review(parser.parse_args().out)
