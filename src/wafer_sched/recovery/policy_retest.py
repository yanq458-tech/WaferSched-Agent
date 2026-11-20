"""Paired AB/BA retest on the frozen 120 snapshots. No archived answers guide the agent."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
import random
from pathlib import Path
from statistics import median

from .continuation import Continuation, delta
from .dispatch import replay_incident
from .evidence_study import ROOT, run_case, save
from .model import dimensions
from .replay import replay_recovery

OUT = Path("results/recovery/hard-case-policy")
OLD, NEW = "graph_legacy", "graph_policy"
PROVED = {"FINITE", "INFEASIBLE_AT_ZERO", "UNBOUNDED"}


def pin(core):
    if core is None:
        return
    import os

    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32
        if not kernel.SetProcessAffinityMask(ctypes.c_void_p(-1), ctypes.c_size_t(1 << core)):
            raise OSError("Could not pin benchmark lane")
    else:
        os.sched_setaffinity(0, {core})


def read_case(item):
    path = ROOT / "inputs" / (item["case"] + ".json")
    buf = path.read_bytes()
    if hashlib.sha256(buf).hexdigest() != item["sha256"]:
        raise ValueError(f"Input checksum mismatch for {path}")
    return Continuation.from_dict(json.loads(buf))


def run_lane(items, core, budget, repeats, folder, confirm, methods=(OLD, NEW)):
    old, new = methods
    pin(core)
    for item, reverse in items:
        case = read_case(item)
        first_status = {}
        for rep in range(repeats):
            if rep and confirm and first_status[old] == first_status[new]:
                break
            order = (new, old) if (reverse + rep) % 2 else (old, new)
            for method in order:
                metrics, evidence = run_case(case, method, budget)
                metrics.update(
                    case=item["case"], repeat=rep, core=core, first_in_pair=method == order[0]
                )
                if rep == 0:
                    first_status[method] = metrics["status"]
                save(
                    folder / "runs" / f"{item['case']}-{rep}-{method}.json",
                    dict(metrics=metrics, **evidence),
                )


def benchmark(folder, budget, cores, repeats, confirm=False, methods=(OLD, NEW)):
    items = json.loads((ROOT / "manifest.json").read_text(encoding="utf8"))
    rng = random.Random(7104)
    rng.shuffle(items)
    jobs = [(item, i % 2) for i, item in enumerate(items)]
    if (folder / "runs").exists():
        raise FileExistsError(f"Use a fresh output folder: {folder}")
    save(
        folder / "protocol.json",
        dict(
            budget=budget,
            methods=methods,
            allocation_fraction=0.85,
            cores=cores,
            workers_per_solve=1,
            seed=7104,
            repeats=repeats,
            confirmation="only first-pair classification differences" if confirm else "all",
            source_manifest_sha256=hashlib.sha256(
                (ROOT / "manifest.json").read_bytes()
            ).hexdigest(),
        ),
    )
    with ProcessPoolExecutor(max_workers=len(cores)) as pool:
        futures = [
            pool.submit(
                run_lane, jobs[i :: len(cores)], core, budget, repeats, folder, confirm, methods
            )
            for i, core in enumerate(cores)
        ]
        for f in futures:
            f.result()


def quality(a, b):
    """Partial order for two UNKNOWN answers: maximize lower / minimize upper."""

    def bounds(r):
        return (
            r["lower"] if r["lower"] is not None else float("-inf"),
            -(r["upper"] if r["upper"] is not None else float("inf")),
        )

    old, new = bounds(a), bounds(b)
    if old == new:
        return "equal"
    if all(y >= x for x, y in zip(old, new)):
        return "better"
    if all(y <= x for x, y in zip(old, new)):
        return "worse"
    return "mixed"


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def audit(folder):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf8"))
    protocol = json.loads((folder / "protocol.json").read_text(encoding="utf8"))
    old, new = protocol.get("methods", ("graph_legacy", "graph_policy"))
    all_rows = []
    cases = []
    replayed = 0
    archive = {}
    for folder_name in ("benchmark", "matched30", "stress30"):
        with (ROOT / folder_name / "results.csv").open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["status"] in PROVED:
                    archive.setdefault(row["case"], set()).add(
                        (row["status"], float(row["rho"]) if row["rho"] else None)
                    )
    for item in manifest:
        name = item["case"]
        case = read_case(item)
        p, h = case.prepare()
        pairs = []
        proofs = set(archive.get(name, ()))
        witness_delays = []
        upper_bounds = []
        nr = protocol["repeats"]
        gains = losses = 0
        for rep in range(nr):
            if (
                rep
                and protocol["confirmation"] != "all"
                and pairs[0][old]["status"] == pairs[0][new]["status"]
            ):
                break
            pair = {}
            for method in (old, new):
                data = json.loads(
                    (folder / "runs" / f"{name}-{rep}-{method}.json").read_text(encoding="utf8")
                )
                row = data["metrics"]
                if method in {"graph_refined", "graph_ranked"}:
                    from .terminal_exact import (
                        last_load_bound,
                        terminal_domain,
                        verify_pending,
                        verify_workload,
                    )

                    for event in data["trace"]:
                        if event.get("tool") == "terminal_capacity_workload":
                            assert verify_workload(p, event), (name, event)
                        if event.get("tool") == "terminal_pending_residence":
                            assert verify_pending(p, event), (name, event)
                        if event.get("tool") == "terminal_last_load_bound":
                            expected = last_load_bound(p, terminal_domain(p))
                            assert expected is not None and all(
                                event.get(k) == v for k, v in expected.items()
                            ), (name, event)
                assert (
                    row["case"] == name
                    and row["method"] == method
                    and row["budget"] == protocol["budget"]
                )
                pair[method] = row
                all_rows.append(row)
                if row["raw_status"] in PROVED:
                    proofs.add(
                        (
                            row["raw_status"],
                            data["witness_repair"] if row["raw_status"] == "FINITE" else None,
                        )
                    )
                if row["upper"] is not None:
                    upper_bounds.append(row["upper"])
                if data["schedule"] is not None:
                    r = data["witness_repair"]
                    s = data["schedule"]
                    if row["raw_status"] == "UNBOUNDED":
                        assert r >= h["offset"] + (dimensions(p)[2] + 1) / p.scale
                    check = replay_recovery(p, max(0, delta(r, h["offset"])), s)
                    if not check["valid"]:
                        raise ValueError((name, check["errors"]))
                    assert (
                        abs(data["raw_makespan"] - h["offset"] - s["makespan_tick"] / p.scale)
                        < 1e-8
                    )
                    replay_incident(
                        case,
                        h,
                        dict(witness_repair_delay_seconds=r, makespan_seconds=data["raw_makespan"]),
                        {"verification": check},
                    )
                    witness_delays.append(r)
                    if any(
                        t.get("proof") == "complete_schedule_uses_no_failed_chamber"
                        for t in data["trace"]
                    ):
                        assert all(
                            p.failed_chamber not in (t["source"], t["destination"])
                            for t in s["transfers"]
                        )
                    replayed += 1
            pairs.append(pair)
            assert len(proofs) <= 1, (name, proofs)
            a, b = pair[old], pair[new]
            gains += int(b["status"] in PROVED and a["status"] not in PROVED)
            losses += int(a["status"] in PROVED and b["status"] not in PROVED)
        if witness_delays and upper_bounds:
            assert max(witness_delays) <= min(upper_bounds), (name, "inconsistent bounds")
        assert not (witness_delays and ("INFEASIBLE_AT_ZERO", None) in proofs)
        assert not (upper_bounds and ("UNBOUNDED", None) in proofs)
        a, b = pairs[0][old], pairs[0][new]
        n = len(pairs)
        direction = (
            "consistent_gain"
            if gains == n and n > 1
            else "consistent_loss"
            if losses == n and n > 1
            else "variable"
            if gains or losses
            else "no_proof_change"
        )
        cases.append(
            dict(
                case=name,
                family=item["family"],
                wip=item["wip"],
                pairs=n,
                proof_delta=direction,
                gain_pairs=gains,
                loss_pairs=losses,
                old_first=a["status"],
                new_first=b["status"],
                old_lower=a["lower"],
                new_lower=b["lower"],
                old_upper=a["upper"],
                new_upper=b["upper"],
                pair_outcomes=" | ".join(v[old]["status"] + "/" + v[new]["status"] for v in pairs),
                unknown_bound_changes=" | ".join(
                    quality(v[old], v[new])
                    if v[old]["status"] == v[new]["status"] == "UNKNOWN"
                    else "n/a"
                    for v in pairs
                ),
                old_first_makespan_proved=a["makespan_optimal"],
                new_first_makespan_proved=b["makespan_optimal"],
                unknown_bounds_first=quality(a, b)
                if a["status"] == b["status"] == "UNKNOWN"
                else "",
                first_makespan_delta=(b["makespan"] - a["makespan"])
                if a["status"] == b["status"] == "FINITE" and a["rho"] == b["rho"]
                else None,
                old_seconds=median(x[old]["wall_seconds"] for x in pairs),
                new_seconds=median(x[new]["wall_seconds"] for x in pairs),
            )
        )
    write_csv(folder / "runs.csv", all_rows)
    write_csv(folder / "instances.csv", cases)
    from collections import Counter

    summary = dict(
        instances=len(cases),
        runs=len(all_rows),
        replayed_schedules=replayed,
        paired_counts=dict(Counter(r["proof_delta"] for r in cases)),
    )
    for method in (old, new):
        rows = [r for r in all_rows if r["method"] == method and r["repeat"] == 0]
        summary[method] = dict(
            first_pair_proofs=sum(r["status"] in PROVED for r in rows),
            first_pair_late=sum(r["late"] for r in rows),
            median_wall=median(r["wall_seconds"] for r in rows),
        )
    save(folder / "summary.json", summary)
    lines = [
        f"# {protocol['budget']:g} 秒配对结果",
        "",
        "首轮覆盖全部 120 个输入。总体数字只计首轮，每个输入权重相同。"
        "反序重复用于判断单例变化能否复现。编号与 inputs 中的 JSON 文件同名。",
        "",
        f"旧策略准时证明 {summary[old]['first_pair_proofs']} 个，新策略准时证明 "
        f"{summary[new]['first_pair_proofs']} 个。本组归档方案另行重放 {replayed} 份。",
    ]
    for key, title in (
        ("consistent_gain", "两次均由新策略独自证明"),
        ("consistent_loss", "两次均由旧策略独自证明"),
        ("variable", "出现证明得失，但未在两次中稳定复现"),
    ):
        group = [r for r in cases if r["proof_delta"] == key]
        lines.extend(["", f"## {title}（{len(group)} 个）", ""])
        lines.extend(
            [f"- {r['case']}　{r['pair_outcomes']}（每对为旧 / 新）" for r in group] or ["无。"]
        )
    lines.extend(
        [
            "",
            "## 都未证明边界时，返回的区间是否变化",
            "",
            "下界越大、上界越小越好。以下为首轮观察，逐次复核见 instances.csv。",
        ]
    )
    for key, label in (
        ("better", "新策略区间更强"),
        ("worse", "新策略区间更弱"),
        ("mixed", "上下界各有得失"),
    ):
        group = [r["case"] for r in cases if r["unknown_bounds_first"] == key]
        lines.extend(["", f"{label}（{len(group)} 个）：" + ("、".join(group) or "无") + "。"])
    lines.extend(["", "[全部实例及用时](instances.csv) · [每次运行记录](runs.csv)"])
    (folder / "changes.md").write_text("\n".join(lines) + "\n", encoding="utf8", newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["run", "audit"])
    ap.add_argument("--out", type=Path, default=OUT / "paired1")
    ap.add_argument("--budget", type=float, default=1)
    ap.add_argument("--cores", nargs="+", type=int)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--confirm-discordant", action="store_true")
    ap.add_argument("--refined", action="store_true")
    ap.add_argument("--ranked", action="store_true")
    args = ap.parse_args()
    if args.action == "run":
        benchmark(
            args.out,
            args.budget,
            args.cores or [None],
            args.repeats,
            args.confirm_discordant,
            ("graph_refined", "graph_ranked")
            if args.ranked
            else ("graph_policy", "graph_refined")
            if args.refined
            else (OLD, NEW),
        )
    else:
        audit(args.out)


if __name__ == "__main__":
    main()
