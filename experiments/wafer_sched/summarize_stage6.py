"""Compute descriptive summaries from actual committed Stage 6 results."""

from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import Path
from statistics import mean, stdev

from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.artifacts import _atomic_text
from wafer_sched.agent.skills import SkillRegistry


def summarize(root=Path("results/wafer_sched/stage6")):
    rows = [json.loads(line) for line in (root / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]
    groups = defaultdict(list)
    for path in root.glob("development/*/*/summary.json"):
        scenario, name = path.parent.parts[-2:]
        groups[scenario, name.split("-")[0]].append(json.loads(path.read_text(encoding="utf-8")))
    ablation = []
    for (scenario, planner), values in sorted(groups.items()):
        spans = [item["best_makespan_seconds"] for item in values]
        ablation.append({"scenario": scenario, "planner": planner, "best_makespan_mean": mean(spans),
                        "best_makespan_std": stdev(spans) if len(spans) > 1 else None,
                        "time_to_best_mean_seconds": mean(v["time_to_best_seconds"] for v in values),
                        "total_wall_mean_seconds": mean(v["total_session_wall_seconds"] for v in values),
                        "calls": [v["rounds"] for v in values], "pass_rates": [v["constraint_pass_rate"] for v in values]})
    budget = []
    for path in root.glob("budgets/*/*/summary.json"):
        history = [json.loads(line) for line in (path.parent / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]
        summary = json.loads(path.read_text(encoding="utf-8"))
        budget.append({"scenario": path.parent.parts[-2], "name": path.parent.name,
                       "best_seconds": summary["best_makespan_seconds"], "wall_seconds": summary["total_session_wall_seconds"],
                       "stop_reason": summary["stop_reason"],
                       "cp_attempts": [{"search_limit": r["proposal"]["parameters"]["max_seconds"],
                         "status": (r["result"].get("solver") or {}).get("status"),
                         "objective": (r["result"].get("solver") or {}).get("objective_seconds"),
                         "bound": (r["result"].get("solver") or {}).get("best_bound_seconds"),
                         "solver_seconds": (r["result"].get("solver") or {}).get("solver_seconds"),
                         "experiment_wall_seconds": r["result"]["wall_seconds"]} for r in history if r["proposal"]["proposed_method"] == "cpsat"]})
    test_rows = []
    labels_path = root / "holdout_labels.json"
    labels = {name.replace("\\", "/"): value for name, value in
              (json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}).items()}
    for row in rows:
        if row["study"].startswith("holdout/"):
            solver = row["result"].get("solver") or {}
            test_rows.append({"scenario": row["proposal"]["scenario_id"], "method": row["proposal"]["proposed_method"],
                "parameters": row["proposal"]["parameters"], "span": row["result"]["metrics"].get("makespan_seconds"),
                "verified": row["result"]["verification"]["valid"], "wall": row["result"]["wall_seconds"],
                "solver_status": solver.get("status"), "bound": solver.get("best_bound_seconds"),
                "frozen_cfar": labels.get(row["study"], {}).get("frozen_cfar_choice", False)})
    summary = {"experiment_count": len(rows), "verified_count": sum(r["result"]["verification"]["valid"] for r in rows),
               "ablation": ablation, "budgets": budget, "holdout": test_rows,
               "acceptance_reasons": dict(Counter(r["acceptance"]["reason"] for r in rows)),
               "solver_status_counts": dict(Counter((r["result"].get("solver") or {})["status"] for r in rows if r["result"].get("solver"))),
               "actual_planners": dict(Counter(r["actual_planner"] for r in rows)),
               "numerical_skill_calls": dict(Counter(call["skill"] for r in rows for call in r["result"]["skill_calls"])),
               "repeated_signatures_within_study": 0,
               "total_recorded_experiment_wall_seconds": sum(r["result"]["wall_seconds"] for r in rows)}
    posthoc = SkillRegistry()
    generalization = []
    test_groups = defaultdict(list)
    for record in rows:
        if record["study"].startswith("holdout/"):
            test_groups[record["proposal"]["scenario_id"]].append(record)
    for scenario, records in test_groups.items():
        baseline = next(r for r in records if r["proposal"]["proposed_method"] == "rule"
                        and r["proposal"]["parameters"]["policy"] == "fifo")
        for candidate in records:
            analysis = posthoc.invoke("ExperimentAnalysisSkill", candidate["result"], baseline["result"])
            delta = analysis["makespan_delta_seconds"]
            generalization.append({"scenario": scenario, "candidate_study": candidate["study"],
                "baseline_study": baseline["study"], "analysis": analysis,
                "worse_than_fifo": delta > 1e-7 if delta is not None else None,
                "candidate_failed": analysis["candidate_failure"],
                "evaluation_scope": "posthoc_frozen_holdout_not_sent_to_planner"})
    summary["generalization_feedback"] = generalization
    summary["posthoc_analysis_skill_calls"] = posthoc.calls
    for study in {r["study"] for r in rows}:
        signatures = [json.dumps([r["proposal"]["proposed_method"], r["proposal"]["parameters"]], sort_keys=True)
                      for r in rows if r["study"] == study]
        summary["repeated_signatures_within_study"] += len(signatures) - len(set(signatures))
    # Add per-study validity/repetition counts to the common comparison contract.
    comparison_path = root / "comparison.csv"
    with comparison_path.open(encoding="utf-8", newline="") as stream:
        comparison = list(csv.DictReader(stream))
    for item in comparison:
        group = [r for r in rows if r["study"] == item["study"]]
        signatures = [json.dumps([r["proposal"]["proposed_method"], r["proposal"]["parameters"]], sort_keys=True) for r in group]
        item["invalid_experiment_calls"] = sum(not r["result"]["verification"]["valid"] for r in group)
        item["repeated_experiment_calls"] = len(signatures) - len(set(signatures))
        item["numerical_constraint_violation_count"] = sum(r["result"]["verification"].get("constraint_violations") or 0 for r in group)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(comparison[0]) if comparison else ["study"])
    writer.writeheader()
    writer.writerows(comparison)
    _atomic_text(comparison_path, stream.getvalue())
    atomic_record(root / "analysis.json", summary)
    tables = ["# 真实数据自动汇总", "", "| 场景 | 规划器 | 最佳Makespan均值±样本标准差(s) | 找到最佳平均墙钟(s) | 完整研究平均墙钟(s) | 调用数 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for row in ablation:
        tables.append(f"| {row['scenario']} | {row['planner']} | {row['best_makespan_mean']:.3f} ± {row['best_makespan_std']:.3f} | "
                      f"{row['time_to_best_mean_seconds']:.3f} | {row['total_wall_mean_seconds']:.3f} | {row['calls']} |")
    tables.extend(["", "| 预算场景 | 模式 | CP实际尝试(限额/状态/目标/下界) | 最佳合法(s) | 全流程墙钟(s) | 停止原因 |",
                   "| --- | --- | --- | --- | --- | --- |"])
    for row in budget:
        attempts = "; ".join(f"{x['search_limit']}/{x['status']}/{x['objective']}/{x['bound']}" for x in row["cp_attempts"])
        tables.append(f"| {row['scenario']} | {row['name']} | {attempts} | {row['best_seconds']} | {row['wall_seconds']:.3f} | {row['stop_reason']} |")
    tables.extend(["", "| 封存测试场景 | 方法 | 参数 | Makespan(s) | 验证通过 | CP状态/下界 | 冻结CFAR选择 |",
                   "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in test_rows:
        tables.append(f"| {row['scenario']} | {row['method']} | {row['parameters']} | {row['span']} | {row['verified']} | "
                      f"{row['solver_status']}/{row['bound']} | {row['frozen_cfar']} |")
    _atomic_text(root / "analysis_tables.md", "\n".join(tables) + "\n")
    return summary


if __name__ == "__main__":
    print(json.dumps(summarize(), indent=2))
