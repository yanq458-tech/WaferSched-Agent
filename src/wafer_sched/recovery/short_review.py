"""Cross-check historical and paired evidence without feeding it to the timed solver."""

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import median

from .evidence_study import ROOT, save
from .policy_retest import PROVED, write_csv
from .short_diagnostics import OUT


def metrics(base, budget, name, rep, method):
    return json.loads((base / f"paired{budget}/runs/{name}-{rep}-{method}.json").read_bytes())[
        "metrics"
    ]


def main():
    oldbase = Path("results/recovery/tail-ranks")
    rows = []
    diagnostics = {
        r["case"]: r
        for r in csv.DictReader(
            (OUT / "diagnostics.csv").read_text(encoding="utf-8-sig").splitlines()
        )
    }
    for item in json.loads((ROOT / "manifest.json").read_bytes()):
        name = item["case"]
        exact = metrics(oldbase, 30, name, 0, "graph_ranked")
        assert exact["status"] in PROVED
        for budget in (1, 30):
            for rep in range(2 if budget == 1 else 1):
                old = metrics(OUT, budget, name, rep, "graph_ranked")
                new = metrics(OUT, budget, name, rep, "graph_fast")
                hist = metrics(oldbase, budget, name, rep, "graph_ranked")
                for m in (old, new):
                    if m["status"] in PROVED:
                        assert (m["status"], m["rho"]) == (exact["status"], exact["rho"]), name
                        if exact["makespan_optimal"] and m["makespan_optimal"]:
                            assert exact["makespan"] == m["makespan"], name
                rows.append(
                    dict(
                        case=name,
                        budget=budget,
                        repeat=rep,
                        old_archive=hist["status"],
                        old_matched=old["status"],
                        new=new["status"],
                        gain=old["status"] not in PROVED and new["status"] in PROVED,
                        loss=old["status"] in PROVED and new["status"] not in PROVED,
                        old_sec=old["wall_seconds"],
                        new_sec=new["wall_seconds"],
                        slower_same_proof=(
                            new["status"] == old["status"]
                            and new["status"] in PROVED
                            and new["wall_seconds"] >= 1.2 * old["wall_seconds"]
                            and new["wall_seconds"] - old["wall_seconds"] >= 0.05
                        ),
                        rho=new["rho"],
                        makespan=new["makespan"],
                        makespan_optimal=new["makespan_optimal"],
                        worse_makespan=(
                            new["status"] == old["status"] == "FINITE"
                            and new["makespan"] > old["makespan"]
                        ),
                        lost_optimality=(old["makespan_optimal"] and not new["makespan_optimal"]),
                        historic_profile=diagnostics.get(name, {}).get("largest", ""),
                    )
                )
    write_csv(OUT / "comparison.csv", rows)
    summary = []
    for b, i in ((1, 0), (1, 1), (30, 0)):
        group = [r for r in rows if (r["budget"], r["repeat"]) == (b, i)]
        summary.append(
            dict(
                budget=b,
                repeat=i,
                archive_proved=sum(r["old_archive"] in PROVED for r in group),
                matched_proved=sum(r["old_matched"] in PROVED for r in group),
                new_proved=sum(r["new"] in PROVED for r in group),
                new_status=dict(Counter(r["new"] for r in group)),
                gains=[r["case"] for r in group if r["gain"]],
                losses=[r["case"] for r in group if r["loss"]],
                slower=[r["case"] for r in group if r["slower_same_proof"]],
                worse_makespan=[r["case"] for r in group if r["worse_makespan"]],
                lost_optimality=[r["case"] for r in group if r["lost_optimality"]],
                median_old=median(r["old_sec"] for r in group),
                median_new=median(r["new_sec"] for r in group),
                max_new=max(r["new_sec"] for r in group),
            )
        )
    save(OUT / "comparison.json", summary)


if __name__ == "__main__":
    main()
