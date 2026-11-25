"""Check frozen inputs, short-run upper certificates, and every finite witness."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.conflict_evidence import verify_bound
from wafer_sched.recovery.feedback.audit import replay
from wafer_sched.recovery.feedback.learned_study import conflict_check
from wafer_sched.recovery.terminal_exact import last_load_bound, terminal_domain


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent / "value-agent-002"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_inputs():
    rows = []
    for item in read(STUDY / "manifest.json"):
        name = item["case"]
        path = STUDY / "inputs" / (name + ".json")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        incident = Continuation.from_dict(read(path))
        problem, prefix = incident.prepare()
        assert prefix["offset"] == 0 and problem.scale == 8
        folder = HERE / "proofs" / name
        plan = None
        if folder.is_dir():
            source = folder / "verification.json"
            rec = read(source)
            assert rec["snapshot_sha256"] == item["sha256"]
            status, tick = rec["status"], rec["lower_tick"]
            assert rec["upper_tick"] == tick
            assert rec["verified_tick"] == (0 if tick is None else tick + 1)
            if rec["schedule"]:
                plan = read(folder / rec["schedule"])
        else:
            source = STUDY / "runs" / "30" / name / "0-human.json"
            run = read(source)
            cert = run["raw"]["certificate"]
            if run["status"] == "INFEASIBLE_AT_ZERO":
                assert conflict_check(problem, cert)
                status, tick = "IMMEDIATE_INFEASIBLE", None
            else:
                assert run["status"] == "FINITE" and run["lower"] == run["upper"]
                tick = int(run["lower"] * problem.scale)
                assert tick / problem.scale == run["lower"] and verify_bound(problem, cert)
                upper = cert["upper_tick"]
                if upper > tick:
                    bound = last_load_bound(problem, terminal_domain(problem))
                    assert bound is not None
                    upper = min(upper, bound["upper_tick"])
                assert tick == upper
                status, plan = "FINITE_EXACT", run["raw"]["best"]["schedule"]
        assert (status, tick is None, plan is None) in {
            ("FINITE_EXACT", False, False), ("IMMEDIATE_INFEASIBLE", True, True)}
        if plan:
            replay(incident, plan, tick / problem.scale)
        rows.append(dict(case=name, snapshot_sha256=item["sha256"], status=status,
                         repair_tick=tick, repair_delay_s=None if tick is None else tick / problem.scale,
                         evidence=source.relative_to(HERE.parent).as_posix()))
    counts = dict(Counter(row["status"] for row in rows))
    assert len({r["case"] for r in rows}) == len(rows) == 18
    return dict(cohort=STUDY.name, ticks_per_second=8, counts=counts, cases=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rebuild cases.json from verified evidence")
    args = parser.parse_args()
    data = check_inputs()
    index = HERE / "cases.json"
    if args.write:
        index.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        assert data == read(index)
    print("Verified frozen inputs, finite schedule replays, and result index:", data["counts"])
