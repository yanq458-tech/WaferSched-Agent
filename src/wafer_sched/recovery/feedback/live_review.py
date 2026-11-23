"""Audit paired DeepSeek results and price the actual server receipts offline."""

import argparse
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

from ..evidence_study import save
from ..holdout import digest
from ..holdout_review import audit_case, describe, load
from ..policy_retest import PROVED, quality, write_csv
from .live_comparison import ARCHIVE, METHODS

PRICE_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


def effect(old, new):
    if old["status"] in PROVED or new["status"] in PROVED:
        if old["status"] == new["status"]:
            assert old["rho"] == new["rho"]
            return "证明相同"
        assert old["status"] == "UNKNOWN" or new["status"] == "UNKNOWN"
        return "新增证明" if new["status"] in PROVED else "丢失证明"
    return {"better": "区间改善", "equal": "区间相同", "worse": "区间退步",
            "mixed": "上下界互有得失"}[quality(old, new)]


def interval(m):
    if m["status"] == "INFEASIBLE_AT_ZERO":
        return "立即不可行"
    if m["status"] == "UNBOUNDED":
        return "无穷"
    if m["status"] == "FINITE":
        return f'精确 {m["rho"]:g}'
    lower = "无见证" if m["lower"] is None else f'{m["lower"]:g}'
    upper = "无上界" if m["upper"] is None else f'{m["upper"]:g}'
    return f"[{lower}, {upper}]"


def usage_for(root, budget, case, rep, run):
    receipt = root / "receipts" / f"b{budget}" / case / f"{rep}.jsonl"
    calls = [json.loads(line) for line in receipt.read_text(encoding="utf8").splitlines()] if receipt.exists() else []
    assert len(calls) == run["api"]["calls"] <= 1
    if not calls:
        return {}
    call = calls[0]
    assert call["http_status"] == 200 and call["model"] == "deepseek-flash"
    u = call["usage"]
    hit, miss, output = (u[k] for k in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens", "completion_tokens"))
    assert hit + miss == u["prompt_tokens"] and hit + miss + output == u["total_tokens"] == run["api"]["reported_total_tokens"]
    local = datetime.fromisoformat(call["started_at_utc"]).astimezone(timezone(timedelta(hours=8)))
    # This experiment took place on Sunday. Reject other dates until their tariff is verified.
    assert local.date().isoformat() == "2026-11-22" and local.weekday() == 6
    price = (hit * Decimal("0.02") + miss + 4 * output) / 1000000
    return dict(start_utc=call["started_at_utc"], model=call["model"], hit=hit, miss=miss,
                output=output, total=u["total_tokens"], cny=str(price), seconds=call["wall_seconds"])


def review(root, previous=None):
    manifest = load(root / "manifest.json")
    assert digest(root / "manifest.json") == digest(ARCHIVE / "manifest.json")
    assert digest(root / "protocol.json") == load(root / "freeze.json")["protocol"]
    strategy = load(root / "protocol.json").get("strategy")
    goals = strategy == "feedback_objectives"
    async_run = strategy == "local_first_async" or goals
    if previous is not None:
        assert digest(previous / "manifest.json") == digest(root / "manifest.json")
    with ProcessPoolExecutor(max_workers=2) as pool:
        audit = list(pool.map(audit_case, [root] * len(manifest), manifest))
    historical = {a["case"]: a for a in load(ARCHIVE / "audit.json")}
    for a in audit:
        assert not (a["raw_proofs"] and historical[a["case"]]["raw_proofs"] and
                    list(map(list, a["raw_proofs"])) != historical[a["case"]]["raw_proofs"]), a["case"]
    save(root / "audit.json", audit)
    rows, paired, receipts, counts = [], [], [], Counter()
    for item in sorted(manifest, key=lambda x: x["case"]):
        case = item["case"]
        for b in (1, 30):
            base = root / f"b{b}" / case
            old = load(ARCHIVE / f"b{b}" / case / "0-agent.json")["metrics"]
            for rep in range(2 if (base / "1-plain.json").exists() else 1):
                ms = {}
                for method in METHODS:
                    run = load(base / f"{rep}-{method}.json")
                    m = run["metrics"]
                    ms[method] = m
                    counts[f"{b}/{rep}/{method}/{m['status']}"] += 1
                    ev = next((x for x in run["evidence"]["trace"] if x.get("tool") in {"deepseek_first_probe", "deepseek_async_advice", "deepseek_goal"}), {})
                    usage = usage_for(root, b, case, rep, run) if method == "deepseek" else {}
                    overlap = run.get("async_accounting", {}).get("local_exact_overlap_seconds", 0)
                    if goals and ev:
                        assert b == 30 and ev["trigger"] == "completed_local_query"
                        trace = run["evidence"]["trace"]
                        assert any(t["tool"] == "strengthened_fixed_repair" and t["repair_tick"] == ev["active_tick"] for t in trace)
                        actions = [t for t in trace if t["tool"] == "execute_advised_goal"]
                        decision = (ev["decision"] or {}).get("goal")
                        if ev["outcome"] == "applied":
                            assert len(actions) == 1 and actions[0]["goal"] == decision
                        else:
                            assert not actions
                        assert 0 <= overlap <= run["async_accounting"]["request_seconds"] + 1e-6
                    elif async_run and ev:
                        assert b == 30 and ev["trigger"] == "local_grid_no_witness"
                        assert 0 <= overlap <= run["async_accounting"]["request_seconds"] + 1e-6
                        trace = run["evidence"]["trace"]
                        assert any(t.get("tool") == "grid_satisfaction" and t.get("status") == "NO_WITNESS"
                                   and t.get("repair_tick") == ev["active_tick"] for t in trace)
                        if ev["outcome"] == "applied":
                            assert any(t.get("reason") == "async_deepseek_" + ev["decision"]["target"]
                                       and t["repair_tick"] == ev["selected_tick"] for t in trace)
                    observed = {}
                    if goals and usage:
                        record = load(root / "receipts" / f"b{b}" / case / f"{rep}.jsonl")
                        raw = json.loads(record["response"]["choices"][0]["message"]["content"])
                        observed = dict(provider_goal=raw.get("goal"), provider_reason=raw.get("reason"))
                    if usage:
                        receipts.append(dict(case=case, budget=b, repeat=rep, outcome=ev["outcome"],
                                             waited=ev["waited_seconds"], local_exact_overlap_seconds=overlap, **observed, **usage))
                    assert bool(usage) == bool(ev)
                    d = ev.get("decision") or {}
                    rows.append(dict(case=case, repeat=rep, **m, answer=interval(m),
                                     api=ev.get("outcome", "未请求"), target=d.get("goal",d.get("target")), tool=d.get("tool"), model_reason=d.get("reason"),
                                     api_wait_seconds=ev.get("waited_seconds", 0), tokens=usage.get("total", 0),
                                     local_exact_overlap_seconds=overlap, reason=describe(run)))
                paired.append(dict(case=case, budget=b, repeat=rep, historical_offline=interval(old),
                                   plain=interval(ms["plain"]), agent=interval(ms["agent"]),
                                   deepseek=interval(ms["deepseek"]), vs_plain=effect(ms["plain"], ms["deepseek"]),
                                   vs_offline=effect(ms["agent"], ms["deepseek"]), vs_archive=effect(old, ms["deepseek"])))
                if goals and b == 1:
                    assert not any(r["tokens"] for r in rows[-len(METHODS):])
                if previous is not None:
                    prior = previous / f"b{b}" / case / f"{rep}-deepseek.json"
                    historic = load(prior)["metrics"] if prior.exists() else None
                    paired[-1].update(previous_live=interval(historic) if historic else None,
                                      vs_previous_live=effect(historic, ms["deepseek"]) if historic else None)
    assert len(receipts) == len(list((root / "receipts").rglob("*.jsonl")))
    write_csv(root / "runs.csv", rows)
    write_csv(root / "paired.csv", paired)
    if receipts:
        write_csv(root / "usage.csv", receipts)
    usage = {}
    for label, group in [("total", receipts)] + [(f"b{b}", [r for r in receipts if r["budget"] == b]) for b in (1, 30)]:
        usage[label] = dict(calls=len(group), **{k:sum(r[k] for r in group) for k in ("hit", "miss", "output", "total")},
                            cny=str(sum(Decimal(r["cny"]) for r in group)), outcomes=dict(Counter(r["outcome"] for r in group)),
                            median_api_seconds=median(r["seconds"] for r in group) if group else None)
    local_overlap = sum(r["local_exact_overlap_seconds"] for r in receipts)
    save(root / "summary.json", dict(counts=dict(counts), runs=len(rows), usage=usage, price_source=PRICE_URL,
                                    local_exact_overlap_seconds=local_overlap,
                                    complete_request_seconds=sum(r["seconds"] for r in receipts),
                                    replay_occurrences=sum(a["schedule_occurrences"] for a in audit),
                                    unique_replays=sum(a["unique_replays"] for a in audit),
                                    distinct_certificates=sum(a["distinct_certificates"] for a in audit)))
    title = "本地优先、停滞后异步咨询 DeepSeek" if async_run else "DeepSeek 参与第一次查询的配对实验"
    lines = ["# " + title, "",
             "18 个冻结快照。单位为故障后的秒数。方括号为尚未证明精确边界的上下界。无见证表示尚无按时验证的可行下界。",
             "所有方法按返回结果的墙钟时间评分。1 秒全部反序复测，30 秒仅首轮判决不同时反序复测。HTTP 回执收尾不参与后续求解。",
             "归因以同期对照为准。相同判决可能耗时不同。限时运行有波动，区间改善与新增证明分开计数。", ""]
    if goals:
        lines += ["1 秒纯本地。30 秒在第一份定时刻精确查询已有回执、区间未闭合时，才异步咨询。模型接收已证上下界、查询状态、搜索量和剩余时间；只可选找见证、收紧上界或沿用本地。",
                  "后台请求期间本地继续运行容量松弛或定时刻搜索；已闭合的结论不受模型影响。理由是模型的答复，数学结果以重放与求解记录为准。", ""]
    elif async_run:
        lines += ["1 秒走原离线图。30 秒先执行本地直接优化和构造。构造未找到方案、边界仍有空隙、有可选的新查询且至少还剩 2 秒时，才在后台咨询一次。",
                  "本地当即继续原定精确查询。模型仅可建议下一次查询，已经查过或已在区间外的建议会被丢弃。请求与本地精确查询的实测重叠见 usage.csv。",
                  f"后台请求与本地精确查询累计重叠 {local_overlap:.3f} 秒（按各实例分别计时再相加）。", ""]
    for b in (1, 30):
        lines += [f"## {b} 秒逐例结果", "", "|快照|轮次|普通函数|离线 Agent|DeepSeek|相对普通函数|相对离线 Agent|",
                  "|---|---:|---|---|---|---|---|"]
        for p in paired:
            if p["budget"] == b:
                lines.append("|" + "|".join(str(p[k]) for k in ("case","repeat","plain","agent","deepseek","vs_plain","vs_offline")) + "|")
    lines += ["", "## 历史 7 个 UNKNOWN 的本轮 30 秒结果", "",
              "|快照|原离线结果|本轮普通函数|本轮离线 Agent|本轮 DeepSeek|模型选项|预算内结果说明|", "|---|---|---|---|---|---|---|"]
    for p in paired:
        if p["budget"] != 30 or p["repeat"] or not p["historical_offline"].startswith("["):
            continue
        r = next(r for r in rows if r["case"] == p["case"] and r["repeat"] == 0 and r["budget"] == 30 and r["method"] == "deepseek")
        lines.append("|" + "|".join([p["case"], p["historical_offline"],p["plain"],p["agent"],p["deepseek"],
                                      str(r["target"] or r["api"])+" "+str(r["tool"] or ""),r["reason"]]) + "|")
    if previous is not None:
        lines += ["", "## 与所指定的上一批在线策略逐例对照（首轮）", "",
                  "|快照|预算（秒）|上次在线|本次在线|变化|", "|---|---:|---|---|---|"]
        for p in paired:
            if not p["repeat"]:
                lines.append("|" + "|".join(str(p[k]) for k in ("case","budget","previous_live","deepseek","vs_previous_live")) + "|")
    lines += ["", f"本批共 {len(rows)} 次方法运行，实际请求 {len(receipts)} 次，合计 {usage['total']['total']} Token，按周日空闲时段估算 ¥{usage['total']['cny']}。含反序复测和迟到回复。"]
    (root / "instances.md").write_text("\n".join(lines)+"\n", encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--previous-live", type=Path)
    args = parser.parse_args()
    review(args.root, args.previous_live)
