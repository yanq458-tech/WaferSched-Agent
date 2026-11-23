"""Post-run evidence audit and paired, per-instance holdout report."""

import argparse
import hashlib
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import median

from . import terminal_exact
from .feedback.exclusive_check import verify as verify_exclusive
from .conflict_evidence import verify_bound
from .continuation import Continuation, delta
from .dispatch import replay_incident
from .evidence_study import save
from .holdout import OUT, digest
from .model import dimensions
from .policy_retest import PROVED, write_csv, quality
from .replay import replay_recovery


def load(path):
    return json.loads(path.read_bytes())


def describe(run):
    m = run["metrics"]
    if m["status"] != "UNKNOWN":
        return ""
    ph = run["phases"]
    names = {
        "snapshot": "快照准备",
        "build": "模型构建",
        "rank_encode_extract": "序号编码",
        "cp_sat": "精确搜索",
        "replay": "方案重放",
        "construct": "见证构造",
        "other": "其余流程",
    }
    largest = max(ph, key=ph.get)
    parts = [f"{names.get(largest, largest)}占时最多 {ph[largest]:.3f}s"]
    if m["late"]:
        parts.append(f"整次返回 {m['wall_seconds']:.3f}s 超时，原始状态 {m['raw_status']}")
    trace = run["evidence"]["trace"]
    calls = run["calls"]
    if calls:
        parts.append("求解回执 " + "/".join(c["status"] for c in calls))
        parts.append(f"分支 {sum(c['branches'] for c in calls)}")
    if m["raw_status"] == "UNKNOWN":
        if run["evidence"]["raw_verified"]:
            parts.append("已有可行方案，上界未闭合")
        elif calls:
            parts.append("未得到可重放见证或不可行证明")
        elif not trace:
            parts.append("进入有日志的查询前内部预算已尽")
        else:
            parts.append("未找到完成方案或排除全部方案")
    if trace:
        healthy = next(
            (x.get("outcome") for x in trace if x.get("tool") == "healthy_completion"), None
        )
        if healthy:
            parts.append("健康腔构造 " + healthy)
    return "；".join(parts)


def audit_case(root, item):
    methods = load(root / "protocol.json")["methods"]
    name = item["case"]
    src = root / "inputs" / f"{name}.json"
    assert digest(src) == item["sha256"]
    case = Continuation.from_dict(load(src))
    p, h = case.prepare()
    domain = terminal_exact.terminal_domain(p)
    proofs = set()
    checked = set()
    n_schedules = 0
    certificates = set()
    delays = []
    uppers = []
    optimum = {}
    observed = {}
    for budget in (1, 30):
        folder = root / f"b{budget}" / name
        first = [load(folder / f"0-{method}.json")["metrics"]["status"] for method in methods]
        reps = 2 if budget == 1 or len(set(first)) > 1 else 1
        assert len(list(folder.glob("*.json"))) == reps * len(methods)
        for rep in range(reps):
            for method in methods:
                run = load(folder / f"{rep}-{method}.json")
                m, e = run["metrics"], run["evidence"]
                assert (m["method"], m["budget"], run["case"], run["repeat"]) == (
                    method,
                    budget,
                    name,
                    rep,
                )
                if rep:
                    assert run["order"] == list(
                        reversed(load(folder / f"0-{method}.json")["order"])
                    )
                assert m["status"] == (
                    m["raw_status"] if m["wall_seconds"] <= budget else "UNKNOWN"
                )
                cert = e["certificate"]
                if cert:
                    key = json.dumps(cert, sort_keys=True)
                    if key not in certificates:
                        check = {
                            "exclusive_terminal_deadlines": verify_exclusive,
                            "terminal_capacity_workload": terminal_exact.verify_workload,
                            "terminal_pending_residence": terminal_exact.verify_pending,
                        }.get(cert["kind"], verify_bound)
                        assert check(p, cert), (name, cert)
                        certificates.add(key)
                for event in e["trace"]:
                    if event.get("tool") == "terminal_last_load_bound":
                        expected = terminal_exact.last_load_bound(p, domain)
                        assert expected and all(event[k] == v for k, v in expected.items())
                if m["raw_status"] in PROVED:
                    proofs.add(
                        (
                            m["raw_status"],
                            e["witness_repair"] if m["raw_status"] == "FINITE" else None,
                        )
                    )
                if m["upper"] is not None:
                    uppers.append(m["upper"])
                dual_ok=False
                for event in e["trace"]:
                    if event.get("tool")=="joint_age_flow_dual" and event["status"]=="INFEASIBLE":
                        from .feedback.branch_probe import restrict,validated_scope
                        from .feedback.age_flow import build as build_flow
                        from .feedback.flow_price import exact_lower
                        scope=event["scope"]
                        archived=load(root/"protocol.json")["scope_dir"]
                        if validated_scope(root,Path(archived))!=(name,scope):
                            raise ValueError("Mismatched complement")
                        subset=restrict(domain,scope["wafer"],scope["chamber"])
                        model,_=build_flow(subset,event["quantum"])
                        value=exact_lower(model.proto,event["prices"],event["denominator"])
                        assert value==event["numerator"] and value>0
                        dual_ok=True
                if m["raw_status"] == "INFEASIBLE_AT_ZERO":
                    assert (
                        cert
                        and cert["kind"]
                        in {"terminal_capacity_workload", "terminal_pending_residence", "exclusive_terminal_deadlines"}
                    ) or dual_ok or any(c["status"] == "INFEASIBLE" for c in run["calls"])
                if m["raw_status"] in {"UNBOUNDED", "FINITE"}:
                    assert e["raw_verified"] and e["schedule"]
                if e["schedule"]:
                    n_schedules += 1
                    r = e["witness_repair"]
                    delays.append(r)
                    s = e["schedule"]
                    end = e["raw_makespan"]
                    if m["raw_status"] == "UNBOUNDED":
                        assert r >= h["offset"] + (dimensions(p)[2] + 1) / p.scale
                    if any(
                        t.get("proof") == "complete_schedule_uses_no_failed_chamber"
                        for t in e["trace"]
                    ):
                        assert all(
                            p.failed_chamber not in (t["source"], t["destination"])
                            for t in s["transfers"]
                        )
                    assert end == h["offset"] + s["makespan_tick"] / p.scale
                    if m["makespan_optimal"]:
                        optimum.setdefault(r, set()).add(end)
                    observed.setdefault(r, []).append(end)
                    key = hashlib.sha256(
                        json.dumps([r, end, s], sort_keys=True).encode()
                    ).hexdigest()
                    if key not in checked:
                        v = replay_recovery(p, max(0, delta(r, h["offset"])), s)
                        assert v["valid"], (name, v["errors"])
                        replay_incident(
                            case,
                            h,
                            dict(witness_repair_delay_seconds=r, makespan_seconds=end),
                            {"verification": v},
                        )
                        checked.add(key)
    assert len(proofs) <= 1, (name, proofs)
    assert not (delays and ("INFEASIBLE_AT_ZERO", None) in proofs)
    assert not (uppers and ("UNBOUNDED", None) in proofs)
    if delays and uppers:
        assert max(delays) <= min(uppers)
    for r, values in optimum.items():
        assert len(values) == 1 and min(observed[r]) == next(iter(values))
    return dict(
        case=name,
        raw_proofs=sorted(proofs),
        schedule_occurrences=n_schedules,
        unique_replays=len(checked),
        distinct_certificates=len(certificates),
    )


def review(root):
    methods = load(root / "protocol.json")["methods"]
    items = load(root / "manifest.json")
    assert digest(root / "manifest.json") == load(root / "freeze.json")["manifest"]
    audit = []
    with ProcessPoolExecutor(max_workers=2) as pool:
        for x in pool.map(audit_case, [root] * len(items), items):
            audit.append(x)
    save(root / "audit.json", audit)
    flat = []
    paired = []
    summary = []
    lines = [
        "# 新快照逐例对照",
        "",
        "编号中的 m、h 表示中、高竞争，t、f、b 表示紧期限、临界期限、可绕行设计。编号末位区分独立种子。输入分组仅表示生成条件。",
        "",
        "表中 ✓ 表示按时证明；? 表示 UNKNOWN。各组顺序为 "
        + " / ".join(methods)
        + "。墙钟超预算按 UNKNOWN 计。配对增退以首轮为主。",
    ]
    for budget in (1, 30):
        lines.extend(
            [
                "",
                f"## {budget} 秒",
                "",
                "| 快照 | 首轮 | 反序 | Agent 首轮相对固定组合 | Agent 首轮 UNKNOWN 的实测情况 |",
                "|---|---|---|---|---|",
            ]
        )
        for item in items:
            name = item["case"]
            folder = root / f"b{budget}" / name
            records = {}
            for path in sorted(folder.glob("*.json")):
                run = load(path)
                r = run["metrics"]
                method = r["method"]
                rep = run["repeat"]
                row = dict(
                    case=name,
                    pressure=item["pressure"],
                    regime=item["regime"],
                    wip=item["wip"],
                    repeat=rep,
                    **r,
                    reason=describe(run),
                    tools=" / ".join(x["tool"] for x in run["evidence"]["trace"] if "tool" in x),
                    cp_status="/".join(c["status"] for c in run["calls"]),
                    **{
                        f"sec_{k}": run["phases"].get(k, 0.0)
                        for k in ("snapshot", "construct", "build", "cp_sat", "replay", "other")
                    },
                )
                flat.append(row)
                records[rep, method] = row
            for (rep, m), agent in records.items():
                if m != "agent":
                    continue
                for base in methods[:-1]:
                    b = records[rep, base]
                    both = agent["status"] in PROVED and b["status"] in PROVED
                    effect = (
                        "新增证明"
                        if agent["status"] in PROVED and not both
                        else "丢证明"
                        if b["status"] in PROVED and not both
                        else "均证明"
                        if both
                        else "均未知"
                    )
                    paired.append(
                        dict(
                            case=name,
                            budget=budget,
                            repeat=rep,
                            baseline=base,
                            effect=effect,
                            agent=agent["status"],
                            control=b["status"],
                            agent_sec=agent["wall_seconds"],
                            control_sec=b["wall_seconds"],
                            sec_delta=agent["wall_seconds"] - b["wall_seconds"],
                            interval=quality(b, agent) if effect == "均未知" else "",
                            makespan_delta=agent["makespan"] - b["makespan"]
                            if both and agent["status"] == "FINITE"
                            else None,
                            lost_makespan_optimal=both
                            and b["makespan_optimal"]
                            and not agent["makespan_optimal"],
                            agent_reason=agent["reason"],
                            control_reason=b["reason"],
                        )
                    )

            def symbols(rep):
                if (rep, "agent") not in records:
                    return "—"
                return " / ".join(
                    "✓" if records[rep, m]["status"] in PROVED else "?" for m in methods
                )

            rel = next(
                r["effect"]
                for r in reversed(paired)
                if r["baseline"] == "fixed" and r["repeat"] == 0 and r["case"] == name
            )
            lines.append(
                f"| {name} | {symbols(0)} | {symbols(1)} | {rel} | {records[0, 'agent']['reason'] or '—'} |"
            )
        for m in methods:
            values = [r for r in flat if (r["method"], r["budget"], r["repeat"]) == (m, budget, 0)]
            summary.append(
                dict(
                    budget=budget,
                    method=m,
                    proved=sum(r["status"] in PROVED for r in values),
                    status=dict(Counter(r["status"] for r in values)),
                    late=sum(r["late"] for r in values),
                    median_sec=median(r["wall_seconds"] for r in values),
                )
            )
    write_csv(root / "runs.csv", flat)
    write_csv(root / "paired.csv", paired)
    save(root / "summary.json", summary)
    effects = []
    for budget in (1, 30):
        for baseline in methods[:-1]:
            cases = [
                r
                for r in paired
                if r["budget"] == budget and r["baseline"] == baseline and r["repeat"] == 0
            ]
            same = [r for r in cases if r["effect"] == "均证明"]
            effects.append(
                dict(
                    budget=budget,
                    baseline=baseline,
                    gains=[r["case"] for r in cases if r["effect"] == "新增证明"],
                    losses=[r["case"] for r in cases if r["effect"] == "丢证明"],
                    same_proof_count=len(same),
                    same_proof_median_agent_minus_control_seconds=median(
                        r["sec_delta"] for r in same
                    )
                    if same
                    else None,
                    slower_same_proof=[
                        r["case"]
                        for r in same
                        if r["sec_delta"] >= 0.05 and r["agent_sec"] >= 1.2 * r["control_sec"]
                    ],
                    weaker_interval=[r["case"] for r in cases if r["interval"] == "worse"],
                    stronger_interval=[r["case"] for r in cases if r["interval"] == "better"],
                    mixed_interval=[r["case"] for r in cases if r["interval"] == "mixed"],
                    longer_finite_schedule=[
                        r["case"] for r in same if (r["makespan_delta"] or 0) > 0
                    ],
                    lost_optimality=[r["case"] for r in same if r["lost_makespan_optimal"]],
                )
            )
    save(root / "paired-effects.json", effects)
    lines.extend(
        [
            "",
            "## 未闭合边界的进展",
            "",
            "同一快照上两档预算分别运行。区间单位为秒，问号表示该端没有在预算内获得证据。下界来自合法方案；有限上界来自数学约束或求解器。",
            "",
            "| 快照 | 1 秒 Agent 区间 | 30 秒 Agent 区间 | 30 秒首轮求解情况 |",
            "|---|---|---|---|",
        ]
    )
    for item in items:
        a, b = [
            next(
                r
                for r in flat
                if r["case"] == item["case"]
                and r["repeat"] == 0
                and r["method"] == "agent"
                and r["budget"] == budget
            )
            for budget in (1, 30)
        ]
        if a["status"] != "UNKNOWN" and b["status"] != "UNKNOWN":
            continue

        def interval(r):
            if r["status"] != "UNKNOWN":
                return r["status"]
            return (
                "["
                + ", ".join("?" if r[k] is None else f"{r[k]:g}" for k in ("lower", "upper"))
                + "]"
            )

        lines.append(
            f"| {a['case']} | {interval(a)} | {interval(b)} | {b['reason'] or b['status']} |"
        )
    lines.extend(
        [
            "",
            "## 逐例配对得失",
            "",
            "相对各直接调用对照列出首轮分类增退和未证区间变化。同一输入反序运行的结果单列在 paired.csv。",
        ]
    )
    for r in effects:
        lines.extend(["", f"### {r['budget']} 秒相对 {r['baseline']}", ""])
        for field, label in (
            ("gains", "新增边界证明"),
            ("losses", "丢失边界证明"),
            ("stronger_interval", "均未知时区间更强"),
            ("weaker_interval", "均未知时区间更弱"),
            ("mixed_interval", "区间各有得失"),
            ("slower_same_proof", "同证用时增加至少 20% 且至少 50 毫秒"),
            ("longer_finite_schedule", "同一有限边界处完工时间变长"),
        ):
            lines.append(f"- {label}：{'、'.join(r[field]) or '无'}。")
    (root / "instances.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    unknown = [r for r in flat if r["status"] == "UNKNOWN"]
    if unknown:
        write_csv(root / "unknown.csv", unknown)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=OUT)
    review(ap.parse_args().root)
