"""Replay boundary witnesses, archive next-tick models, and compare the frozen controls."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from ortools.sat.python import cp_model

from .confirm_regressions import flags
from .continuation import delta
from .dispatch import replay_incident
from .evidence_study import ROOT, save
from .policy_retest import PROVED, pin, quality, read_case, write_csv
from .replay import replay_recovery
from .tail_ranks import rank_bound, solve_rank
from .terminal_diagnostics import profile
from .terminal_exact import terminal_domain

OUT = Path("results/recovery/tail-ranks")
PRIOR = Path("results/recovery/terminal-proofs/accepted")
TARGETS = ("terminal-08-04", "terminal-12-02", "terminal-12-08")
OLD, NEW = "graph_refined", "graph_ranked"


def read(path):
    return json.loads(path.read_bytes())


def proof_files(out, items, seconds):
    folder = out / "proofs"
    folder.mkdir(parents=True, exist_ok=True)
    for name in TARGETS:
        data = read(out / "paired30" / "runs" / f"{name}-0-{NEW}.json")
        if data["metrics"]["status"] != "FINITE":
            save(
                folder / f"{name}.json",
                dict(
                    status=data["metrics"]["status"],
                    lower=data["metrics"]["lower"],
                    upper=data["metrics"]["upper"],
                ),
            )
            continue
        case = read_case(items[name])
        p, h = case.prepare()
        domain = terminal_domain(p)
        jobs, P, L, d = domain
        r = data["witness_repair"]
        scale = p.scale
        tick = round(delta(r, h["offset"]) * scale)
        assert h["offset"] + tick / scale == r
        schedule = data["schedule"]
        checked = replay_recovery(p, tick / scale, schedule)
        assert checked["valid"]
        replay_incident(
            case,
            h,
            dict(witness_repair_delay_seconds=r, makespan_seconds=data["raw_makespan"]),
            {"verification": checked},
        )
        save(folder / f"{name}-schedule.json", schedule)
        write_csv(
            folder / f"{name}-schedule.csv",
            [
                dict(
                    wafer=t["wafer_id"],
                    stage=t["stage"],
                    source=t["source"],
                    destination=t["destination"],
                    **{
                        key + "_seconds": h["offset"] + t[key] / scale
                        for key in ("pick_start", "pick_end", "place_start", "place_end")
                    },
                )
                for t in schedule["transfers"]
            ],
        )
        q = tick + 1
        pack = rank_bound(p, domain)
        last = pack["wafer"] if q > pack["split_tick"] else None
        first = min(
            max(j.ready, 0 if j.source == p.snapshot["robot"]["position"] else d) for j in jobs
        )
        period = P + L + 2 * d
        maxdue = max(j.due for j in jobs if last is None or j.wafer == last)
        capacity = len({c for j in jobs for c, _ in j.choices})
        n = len(jobs)
        lo = max(n - 1, 2 * (n - 1) - (capacity - 1))
        hi = min(2 * n - 2, (maxdue - P - first) // period)
        slices = []
        for rank in range(lo, hi + 1):
            k = 2 * (n - 1) - rank
            branch = next((b for b in pack["branches"] if b["pending"] == k), {})
            # For the 12-wafer cases, independently query k=1,2 without the
            # forced-pending/window matching cut. Larger k have a simple sum certificate.
            if last and branch.get("average_upper", q) < q:
                if k > 2:
                    slices.append(
                        dict(
                            rank=rank,
                            pending=k,
                            status="INFEASIBLE",
                            reason="sum_of_residence_windows",
                            upper_tick=branch["average_upper"],
                        )
                    )
                    continue
            artifact = folder / f"{name}-next-rank-{rank}.pb.gz"
            _, row = solve_rank(
                p,
                domain,
                rank,
                q,
                q,
                perf_counter() + seconds,
                last=last,
                fixed=True,
                artifact=artifact,
            )
            if row["status"] in {"FEASIBLE", "OPTIMAL"}:
                raise ValueError((name, "next tick contradicts claimed optimum", row))
            slices.append(dict(pending=k, **row))
        excluded = all(row["status"] == "INFEASIBLE" for row in slices)
        arithmetic = pack["upper_tick"] < q
        if not (excluded or arithmetic):
            raise ValueError((name, "No next-tick proof in diagnostic budget", slices))
        save(
            folder / f"{name}.json",
            dict(
                input_sha256=items[name]["sha256"],
                scale=scale,
                boundary_tick=tick,
                repair_seconds=r,
                next_tick=q,
                next_seconds=h["offset"] + q / scale,
                makespan_seconds=data["raw_makespan"],
                makespan_optimal=data["metrics"]["makespan_optimal"],
                suffix_and_incident_replay=True,
                rank_certificate=pack,
                last_source_ranks=[lo, hi],
                next_tick_excluded_by_slices=excluded,
                next_tick_excluded_by_arithmetic=arithmetic,
                slices=slices,
            ),
        )


def repeat_models(folder, seconds):
    for name in TARGETS:
        doc = read(folder / f"{name}.json")
        for part in doc.get("slices", []):
            if not part.get("model"):
                continue
            raw = gzip.decompress((folder / part["model"]).read_bytes())
            assert hashlib.sha256(raw).hexdigest() == part["model_sha256"]
            m = cp_model.CpModel()
            m.proto.ParseFromString(raw)
            cp = cp_model.CpSolver()
            cp.parameters.num_search_workers = 1
            cp.parameters.random_seed = 0
            cp.parameters.max_time_in_seconds = seconds
            status = cp.status_name(cp.solve(m))
            if status in {"OPTIMAL", "FEASIBLE", "MODEL_INVALID"}:
                raise RuntimeError((name, part["rank"], status))
            print(name, part["rank"], status, flush=True)


def kim_profile(folder, item):
    case = read_case(item)
    rows = []
    for budget in (1, 30):
        for rep in range(6):
            for method in (OLD, NEW) if rep % 2 == 0 else (NEW, OLD):
                rows.append(dict(budget=budget, repeat=rep, **profile(case, method, budget)))
    historical = []
    for rep in range(2):
        record = read(PRIOR / "paired1" / "runs" / f"kim-22-{rep}-{OLD}.json")
        historical.append({k: record[k] for k in ("metrics", "trace")})
    summaries = []
    for budget in (1, 30):
        for method in (OLD, NEW):
            arm = [row for row in rows if (row["budget"], row["method"]) == (budget, method)]
            summaries.append(
                dict(
                    budget=budget,
                    method=method,
                    repeats=len(arm),
                    on_time_proofs=sum(row["metrics"]["status"] in PROVED for row in arm),
                    wall=median(row["metrics"]["wall_seconds"] for row in arm),
                    **{
                        k: median(row["phases"].get(k, 0) for row in arm)
                        for k in ("snapshot", "build", "cp_sat", "replay", "other")
                    },
                    calls=[row["counts"] for row in arm],
                )
            )
    save(folder / "kim-22-profile.json", dict(archived=historical, summary=summaries, runs=rows))


def compare(folder):
    rows = []
    for b in (1, 30):
        paired = folder / f"paired{b}"
        groups = {}
        secondary = read(paired / "secondary" / "results.json")
        for f in (paired / "runs").glob("*.json"):
            row = read(f)["metrics"]
            groups.setdefault(row["case"], {}).setdefault(row["repeat"], {})[row["method"]] = row
        for name, pairs in sorted(groups.items()):
            a, best = pairs[0][OLD], pairs[0][NEW]
            historic = read(PRIOR / "paired30" / "runs" / f"{name}-0-{OLD}.json")["metrics"]
            all_runs = [historic] + [v for pair in pairs.values() for v in pair.values()]
            proofs = {(r["status"], r["rho"]) for r in all_runs if r["status"] in PROVED}
            assert len(proofs) <= 1, (name, proofs)
            bounds = [r["upper"] for r in all_runs if r["upper"] is not None]
            lowers = [r["lower"] for r in all_runs if r["lower"] is not None]
            assert not lowers or not bounds or max(lowers) <= min(bounds)
            assert not (lowers and ("INFEASIBLE_AT_ZERO", None) in proofs)
            assert not (bounds and ("UNBOUNDED", None) in proofs)
            effects = [flags(pair[OLD], pair[NEW]) for _, pair in sorted(pairs.items())]
            reverse = (
                effects[1] if len(effects) > 1 else secondary.get(name, {}).get("retest_effect")
            )
            same = [
                (p[OLD], p[NEW])
                for p in pairs.values()
                if p[OLD]["status"] == p[NEW]["status"] == "FINITE"
            ]
            rows.append(
                dict(
                    budget=b,
                    case=name,
                    old=a["status"],
                    new=best["status"],
                    old_time=a["wall_seconds"],
                    new_time=best["wall_seconds"],
                    first_effect=effects[0],
                    reverse_effect=reverse,
                    stable_slow=effects[0] == reverse == "slower_same_proof",
                    optimum_lost_any=any(
                        x["makespan_optimal"] and not y["makespan_optimal"] for x, y in same
                    ),
                    worse_makespan_any=any(y["makespan"] > x["makespan"] for x, y in same),
                    unknown_quality=quality(a, best)
                    if a["status"] == best["status"] == "UNKNOWN"
                    else "",
                )
            )
    write_csv(folder / "paired-effects.csv", rows)
    import platform
    from importlib.metadata import version

    source = Path(__file__).parent
    names = (
        "tail_ranks.py",
        "study_policy.py",
        "conflict_evidence.py",
        "evidence_study.py",
        "policy_retest.py",
        "rank_review.py",
    )
    save(
        folder / "provenance.json",
        dict(
            control_commit="6b6bfa955a3ec723639e59ab6837aeca94681369",
            manifest_sha256=hashlib.sha256((ROOT / "manifest.json").read_bytes()).hexdigest(),
            python=platform.python_version(),
            ortools=version("ortools"),
            langgraph=version("langgraph"),
            source_sha256={
                name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names
            },
        ),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["proofs", "recheck", "profile", "compare"])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--seconds", type=float, default=30)
    args = ap.parse_args()
    pin(2)
    items = {it["case"]: it for it in read(ROOT / "manifest.json")}
    if args.action == "proofs":
        proof_files(args.out, items, args.seconds)
    elif args.action == "recheck":
        repeat_models(args.out / "proofs", args.seconds)
    elif args.action == "profile":
        kim_profile(args.out, items["kim-22"])
    else:
        compare(args.out)


if __name__ == "__main__":
    main()
