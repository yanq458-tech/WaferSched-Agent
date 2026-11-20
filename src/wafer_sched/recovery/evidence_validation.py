"""Cross-check fixed-delay and lexicographic objectives using independent backends."""

import json
from pathlib import Path
from .conflict_evidence import best_bound, verify_bound
from .continuation import Continuation
from .direct import direct
from .dispatch import recover
from .evidence_study import save
from .incidents import scenarios
from .milp_reference import reference_incident
from .primitive_oracle import enumerate_incident


def validate(root):
    cases = scenarios()
    cases["fractional"] = Continuation.from_dict(
        json.loads(Path("data/recovery-study/fractional-seed.json").read_text())
    )
    boundaries, checks, certificates = [], [], {}
    for name, case in cases.items():
        plain = direct(case, 8, cuts=False)
        certified = direct(case, 8)
        binary = recover(case, "boundary", per_query=4, total=12, optimized=False)
        keys = ("status", "latest_repair_delay_seconds")
        if len({tuple(r.get(k) for k in keys) for r in (plain, certified, binary)}) != 1:
            raise AssertionError((name, plain["status"], certified["status"], binary["status"]))
        row = dict(
            case=name,
            status=plain["status"],
            rho=plain.get(keys[1]),
            raw_direct=plain["trace"] if "trace" in plain else [],
            binary_queries=len(binary.get("suffix_search", {}).get("history", [])),
            makespan=plain.get("makespan_seconds"),
            direct_cut_trace=certified.get("trace"),
        )
        boundaries.append(row)
        if plain["status"] == "UNSUPPORTED":
            continue
        p, prefix = case.prepare()
        cert = best_bound(p)
        if cert:
            assert verify_bound(p, cert)
            certificates[name] = dict(offset=prefix["offset"], certificate=cert)
        delays = {0, 2}
        if row["rho"] is not None:
            delays.update([row["rho"], row["rho"] + 1 / p.scale])
        if name == "fractional":
            delays.add(9.3125)
        for delay in sorted(delays):
            exact = recover(case, "solve", repair=delay, per_query=4, optimized=False)
            milp = reference_incident(case, delay, seconds=8)
            oracle = enumerate_incident(case, delay, max_states=250000)
            pair = (exact["status"], exact.get("makespan_seconds"))
            if (milp["status"], milp.get("makespan_seconds")) != pair:
                raise AssertionError(
                    (name, delay, pair, milp["status"], milp.get("makespan_seconds"))
                )
            if (
                oracle["status"] != "UNKNOWN"
                and (oracle["status"], oracle.get("makespan_seconds")) != pair
            ):
                raise AssertionError((name, delay, pair, oracle))
            if row["rho"] == delay:
                assert plain["makespan_optimal"] and certified["makespan_optimal"]
                assert row["makespan"] == pair[1] == certified["makespan_seconds"]
            checks.append(
                dict(
                    case=name,
                    repair=delay,
                    cp_status=pair[0],
                    makespan=pair[1],
                    scip_status=milp["status"],
                    scip_makespan=milp.get("makespan_seconds"),
                    scip_assignments=milp.get("tried"),
                    scip_full_replay=milp.get("verified", False),
                    oracle=oracle,
                )
            )
        save(
            root / "validation" / "witnesses" / f"{name}.json",
            dict(
                schedule=certified.get("best", {}).get("schedule"),
                events=certified.get("executed_events"),
                rho=row["rho"],
                makespan=certified.get("makespan_seconds"),
            ),
        )
    save(root / "validation" / "direct-vs-binary.json", boundaries)
    save(root / "validation" / "milp-vs-oracle.json", checks)
    save(root / "validation" / "certificates.json", certificates)
