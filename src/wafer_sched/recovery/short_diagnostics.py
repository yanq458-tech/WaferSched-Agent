"""Profile the archived first-round misses and either-order proof losses on one core."""

import argparse
import json
from pathlib import Path
from .evidence_study import ROOT, save
from .policy_retest import read_case, pin, PROVED, write_csv
from .terminal_diagnostics import profile

OUT = Path("results/recovery/one-second")
ARCHIVE = Path("results/recovery/tail-ranks/paired1/runs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", type=int, default=2)
    ap.add_argument("--reuse-profiles", action="store_true")
    args = ap.parse_args()
    pin(args.core)
    rows = []
    for item in json.loads((ROOT / "manifest.json").read_bytes()):
        name = item["case"]

        def old(rep, method):
            return json.loads((ARCHIVE / f"{name}-{rep}-{method}.json").read_bytes())["metrics"]

        first = old(0, "graph_ranked")
        loss = any(
            old(i, "graph_ranked")["status"] == "UNKNOWN"
            and old(i, "graph_refined")["status"] in PROVED
            for i in (0, 1)
        )
        if first["status"] != "UNKNOWN" and not loss:
            continue
        path = OUT / "diagnostics" / (name + ".json")
        if args.reuse_profiles:
            runs = json.loads(path.read_bytes())
        else:
            runs = [profile(read_case(item), "graph_ranked", 1) for _ in range(2)]
            save(path, runs)
        phases = {
            k: sum(r["phases"].get(k, 0) for r in runs) / 2
            for k in (
                "snapshot",
                "build",
                "rank_encode_extract",
                "cp_sat",
                "replay",
                "construct",
                "other",
            )
        }
        rows.append(
            dict(
                case=name,
                historic_first=first["status"],
                historic_raw=first["raw_status"],
                historic_loss=loss,
                historic_seconds=first["wall_seconds"],
                reruns="/".join(r["metrics"]["status"] for r in runs),
                largest=max(phases, key=phases.get),
                **phases,
            )
        )
    write_csv(OUT / "diagnostics.csv", rows)


if __name__ == "__main__":
    main()
