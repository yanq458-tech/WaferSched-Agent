"""Isolate the direct objective and the new cuts with the same wall-clock budget."""

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path
from time import perf_counter

from .conflict_evidence import best_bound, verify_bound
from .continuation import Continuation
from .direct import direct
from .dispatch import recover
from .evidence_study import ROOT, save

CASES = (
    "chain-00",
    "chain-05",
    "chain-11",
    "kim-00",
    "kim-01",
    "kim-02",
    "terminal-02-02",
    "terminal-04-01",
    "terminal-06-02",
    "terminal-06-03",
    "terminal-08-00",
    "terminal-12-04",
)


def run(root, budget):
    certs = {}
    rows = []
    rng = random.Random(527)
    for inst in json.loads((root / "manifest.json").read_text(encoding="utf8")):
        name = inst["case"]
        case = Continuation.from_dict(
            json.loads((root / "inputs" / f"{name}.json").read_text(encoding="utf8"))
        )
        p, prefix = case.prepare()
        cert = best_bound(p)
        if cert:
            assert verify_bound(p, cert)
            certs[name] = {
                "certificate": cert,
                "fault_relative_upper": prefix["offset"] + cert["upper_tick"] / p.scale,
            }
        if name not in CASES:
            continue
        methods = ["binary_plain", "direct_plain", "direct_verified_cut"]
        rng.shuffle(methods)
        solved = set()
        for method in methods:
            start = perf_counter()
            if method == "binary_plain":
                out = recover(
                    case, "boundary", total=budget * 0.85, per_query=budget * 0.85, optimized=False
                )
                calls = out.get("suffix_search", {}).get("history", []).copy()
                if "optimization" in out:
                    calls.append(out["optimization"])
            else:
                out = direct(case, budget * 0.85, cuts=method == "direct_verified_cut")
                calls = out["trace"]
            elapsed = perf_counter() - start
            status = out["status"] if elapsed <= budget else "UNKNOWN"
            if out["status"] in ("FINITE", "UNBOUNDED", "INFEASIBLE_AT_ZERO"):
                solved.add((out["status"], out.get("latest_repair_delay_seconds")))
            if cert and out["status"] == "FINITE":
                assert out["latest_repair_delay_seconds"] <= certs[name]["fault_relative_upper"]
            if cert:
                assert out["status"] != "UNBOUNDED"
            rows.append(
                dict(
                    case=name,
                    method=method,
                    status=status,
                    raw_status=out["status"],
                    rho=out.get("latest_repair_delay_seconds") if elapsed <= budget else None,
                    budget=budget,
                    elapsed=elapsed,
                    branches=sum(r["branches"] for r in calls),
                    calls=len(calls),
                    new_certificate_available=bool(cert),
                )
            )
        assert len(solved) <= 1, (name, solved)
    save(root / "ablation" / "certificates.json", certs)
    with (root / "ablation" / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save(
        root / "ablation" / "summary.json",
        dict(
            instances=len(CASES),
            runs=len(rows),
            budget=budget,
            certificate_coverage=dict(Counter(v["certificate"]["kind"] for v in certs.values())),
            methods={
                m: dict(Counter(r["status"] for r in rows if r["method"] == m)) for m in methods
            },
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT)
    parser.add_argument("--budget", type=float, default=2)
    args = parser.parse_args()
    run(args.out, args.budget)
