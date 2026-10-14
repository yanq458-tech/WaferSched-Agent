"""Measured research records, comparable costs, and no invented blocked-arm results."""

import csv
import io
import json
from pathlib import Path
from time import perf_counter

from wafer_sched.artifacts import _atomic_text
from wafer_sched.infrastructure.io import atomic_record


def public_row(row):
    p, r = row["proposal"], row["result"]
    plan, reflection = row.get("planner_call") or {}, row.get("reflection_call") or {}

    def tokens(call):
        return call["usage"]["total_tokens"] if call.get("usage") else None

    return {
        "round": row["global_round"],
        "scenario_round": row["round"],
        "experiment_id": p["experiment_id"],
        "scenario_id": p["scenario_id"],
        "method": p["proposed_method"],
        "parameters": json.dumps(p["parameters"], sort_keys=True),
        "actual_planner": row["actual_planner"],
        "fallback_reason": row.get("fallback_reason"),
        "llm_model": plan.get("model"),
        "planner_call_id": plan.get("call_id"),
        "reflection_call_id": reflection.get("call_id"),
        "planner_tokens": tokens(plan),
        "reflection_tokens": tokens(reflection),
        "verified": r["verification"]["valid"],
        "makespan_seconds": r["metrics"].get("makespan_seconds"),
        "best_so_far_seconds": row["best_so_far_seconds"],
        "tool_wall_seconds": r["wall_seconds"],
        "active_wall_seconds": row["elapsed_seconds"],
        "accepted": row["acceptance"]["accepted"],
        "acceptance_reason": row["acceptance"]["reason"],
        "solver_status": (r.get("solver") or {}).get("status"),
        "solver_seconds": (r.get("solver") or {}).get("solver_seconds"),
        "solver_bound_seconds": (r.get("solver") or {}).get("best_bound_seconds"),
        "selection_reason": p["selection_reason"],
        "hypothesis": p["expected_reason"],
        "evidence": json.dumps(p["evidence_from_history"]),
        "llm_reflection": json.dumps(row.get("llm_reflection"), ensure_ascii=False),
        "next_plan": json.dumps(row.get("next_plan"), ensure_ascii=False),
    }


def session_statistics(records):
    by_scenario = {}
    cumulative_tools = 0.0
    for row in records:
        cumulative_tools += row["result"]["wall_seconds"]
        sid = row["proposal"]["scenario_id"]
        by_scenario.setdefault(sid, []).append((row, cumulative_tools))
    scenarios = {}
    for name, pairs in by_scenario.items():
        valid = [(r, c) for r, c in pairs if r["result"]["verification"]["valid"]]
        best = min(
            (r["result"]["metrics"]["makespan_seconds"] for r, _ in valid), default=None
        )
        first = next(
            (
                (r, c)
                for r, c in valid
                if r["result"]["metrics"]["makespan_seconds"] == best
            ),
            None,
        )
        selected_tool_time = 0.0
        time_at_hit = None
        for row, _ in pairs:
            selected_tool_time += row["result"]["wall_seconds"]
            if first and row["global_round"] == first[0]["global_round"]:
                time_at_hit = selected_tool_time
        signatures = [
            (
                r["proposal"]["proposed_method"],
                json.dumps(r["proposal"]["parameters"], sort_keys=True),
            )
            for r, _ in pairs
        ]
        scenarios[name] = {
            "rounds": len(pairs),
            "verified_rounds": len(valid),
            "best_makespan_seconds": best,
            "first_best_global_round": first[0]["global_round"] if first else None,
            "first_best_scenario_round": first[0]["round"] if first else None,
            "first_best_cumulative_all_tools_seconds": first[1] if first else None,
            "first_best_cumulative_scenario_tools_seconds": time_at_hit,
            "total_scenario_tools_seconds": selected_tool_time,
            "valid_experiment_ratio": len(valid) / len(pairs),
            "repeated_experiment_ratio": (len(signatures) - len(set(signatures)))
            / len(pairs),
        }
    return scenarios, cumulative_tools


def publish_session(root, records, mode, limits, llm_totals, elapsed, stop_reason):
    started = perf_counter()
    scenarios, total_tools = session_statistics(records)
    real = [
        r
        for r in records
        if r["actual_planner"] == "LangGraphLLMPlanner"
        and (r.get("planner_call") or {}).get("evidence_source") == "real_api"
        and (r.get("planner_call") or {}).get("status") == "completed"
    ]
    reflections = [
        r
        for r in real
        if r.get("llm_reflection")
        and (r.get("reflection_call") or {}).get("evidence_source") == "real_api"
    ]
    summary = {
        "arm": mode,
        "status": "paused"
        if stop_reason == "paused_at_experiment_boundary"
        else "completed",
        "stop_reason": stop_reason,
        "rounds": len(records),
        "scenarios": scenarios,
        "real_llm_planned_rounds": len(real),
        "real_llm_reflected_rounds": len(reflections),
        "real_verified_llm_rounds": sum(
            r["result"]["verification"]["valid"] for r in real
        ),
        "minimum_real_llm_rounds": limits.minimum_real_llm_rounds,
        "real_llm_acceptance_passed": len(real) >= limits.minimum_real_llm_rounds
        and len(reflections) >= limits.minimum_real_llm_rounds
        and all(r["result"]["verification"]["valid"] for r in real),
        "total_tools_seconds": total_tools,
        "total_active_research_wall_seconds": elapsed,
        "wall_budget_seconds": limits.total_seconds,
        "cost_scope": "tool subprocess including startup and original verification + second graph replay; "
        "active wall includes planning, memory and graph overhead; suspended downtime and export excluded",
        "all_recorded_candidates_verified": bool(records)
        and all(r["result"]["verification"]["valid"] for r in records),
        "llm": llm_totals,
        "fallback_rounds": sum(bool(r.get("fallback_reason")) for r in records),
        "cp_allocated_search_seconds": sum(
            r["proposal"]["parameters"]["max_seconds"]
            for r in records
            if r["proposal"]["proposed_method"] == "cpsat"
        ),
        "cp_measured_solver_seconds": sum(
            (r["result"].get("solver") or {}).get("solver_seconds", 0) for r in records
        ),
        "source_code_modified_by_llm": False,
        "historical_models_retrained": False,
    }
    if records:
        stream = io.StringIO(newline="")
        rows = [public_row(r) for r in records]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        _atomic_text(Path(root) / "decisions.csv", stream.getvalue())
    atomic_record(Path(root) / "summary.json", summary)
    summary["artifact_export_seconds"] = perf_counter() - started
    atomic_record(Path(root) / "summary.json", summary)
    return summary


def publish_comparison(root, summaries):
    root = Path(root)
    rows = []
    for arm, summary in summaries.items():
        for name in summary.get("scenarios") or {}:
            record = summary["scenarios"][name]
            rows.append(
                {
                    "arm": arm,
                    "scenario_id": name,
                    "status": summary["status"],
                    **record,
                    "total_active_research_wall_seconds": summary[
                        "total_active_research_wall_seconds"
                    ],
                    "total_tools_seconds": summary["total_tools_seconds"],
                    "real_llm_planned_rounds": summary["real_llm_planned_rounds"],
                    "fallback_rounds": summary["fallback_rounds"],
                    "llm_wall_seconds": summary["llm"]["llm_wall_seconds"],
                    "reported_total_tokens": summary["llm"]["reported_total_tokens"],
                    "estimated_peak_api_usd": summary["llm"]["estimated_peak_api_usd"],
                }
            )
    if rows:
        scenario_names = sorted({r["scenario_id"] for r in rows})
        for arm, summary in summaries.items():
            if summary.get("status") == "blocked":
                for name in scenario_names:
                    blocked = dict.fromkeys(rows[0])
                    blocked.update(
                        arm=arm,
                        scenario_id=name,
                        status="blocked",
                        real_llm_planned_rounds=0,
                        fallback_rounds=0,
                    )
                    rows.append(blocked)
    stream = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _atomic_text(root / "comparison.csv", stream.getvalue())
    atomic_record(root / "comparison.json", summaries)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = sorted({r["scenario_id"] for r in rows})
    if not names:
        return
    fig, axes = plt.subplots(
        1, len(names), figsize=(7 * len(names), 4.8), squeeze=False
    )
    for index, name in enumerate(names):
        ax = axes[0, index]
        for arm in summaries:
            path = root / arm / "experiments.jsonl"
            if not path.exists():
                continue
            history = [
                json.loads(s)
                for s in path.read_text(encoding="utf-8").splitlines()
                if s
            ]
            local = [r for r in history if r["proposal"]["scenario_id"] == name]
            if local:
                ax.step(
                    [r["global_round"] for r in local],
                    [r["best_so_far_seconds"] for r in local],
                    where="post",
                    marker="o",
                    label=arm,
                )
        ax.set(
            title=name,
            xlabel="Global experiment round",
            ylabel="Verified best Makespan (s)",
        )
        ax.grid(alpha=0.25)
        ax.legend()
    if "B" in summaries and summaries["B"].get("status") == "blocked":
        fig.suptitle("B: real LLM experiment unavailable; no synthetic B curve")
    fig.tight_layout()
    fig.savefig(root / "best_so_far_comparison.png", dpi=220)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    arms = [a for a, s in summaries.items() if s.get("status") != "blocked"]
    axes[0].bar(
        arms, [summaries[a]["total_tools_seconds"] for a in arms], label="Tool time"
    )
    axes[0].bar(
        arms,
        [summaries[a]["llm"]["llm_wall_seconds"] for a in arms],
        bottom=[summaries[a]["total_tools_seconds"] for a in arms],
        label="LLM time",
    )
    axes[0].set(ylabel="Measured seconds", title="Tool and LLM cost")
    axes[0].legend()
    axes[1].bar(arms, [summaries[a]["llm"]["reported_total_tokens"] for a in arms])
    axes[1].set(ylabel="Provider-reported tokens", title="LLM token usage")
    fig.tight_layout()
    fig.savefig(root / "time_token_costs.png", dpi=220)
    plt.close(fig)
