"""Offline audit of saved stage-seven experiments. Never calls APIs or retrains."""

import argparse
import json

from wafer_sched.agent.skills import replay_decisions
from wafer_sched.config import load_config
from wafer_sched.infrastructure.paths import PROJECT_ROOT
from wafer_sched.langgraph_agent.reporting import session_statistics
from wafer_sched.metrics import calculate_metrics


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path):
    return [
        json.loads(s)
        for s in path.read_text(encoding="utf-8").splitlines()
        if s.strip()
    ]


def verify(root):
    data = {}
    for arm in "ABC":
        directory = root / arm
        manifest = read(directory / "manifest.json")
        summary = read(directory / "summary.json")
        records = lines(directory / "experiments.jsonl")
        assert len(records) == summary["rounds"]
        configs = {
            s["name"]: load_config(PROJECT_ROOT / s["config"])
            for s in manifest["study"]["development"]
        }
        for row in records:
            result = row["result"]
            decisions = read(
                PROJECT_ROOT / result["artifact_directory"] / "decisions.json"
            )["decisions"]
            sim = replay_decisions(
                configs[row["proposal"]["scenario_id"]],
                decisions,
                result["window_seconds"],
                result["seed"],
            )
            assert sim.completed and sim.validate_state()
            assert calculate_metrics(sim.trace) == result["metrics"]
            assert (
                result["verification"]["valid"]
                and result["verification"]["graph_replay_verified"]
            )
        scenarios, total = session_statistics(records)
        assert (
            scenarios == summary["scenarios"]
            and total == summary["total_tools_seconds"]
        )
        if arm == "B":
            calls = lines(directory / "llm_calls.jsonl")
            indexed = {r["call_id"]: r for r in calls}
            for row in records:
                assert row["actual_planner"] == "LangGraphLLMPlanner" and not row.get(
                    "fallback_reason"
                )
                call = indexed[row["planner_call"]["call_id"]]
                assert (
                    call["evidence_source"] == "real_api"
                    and call["status"] == "completed"
                    and call["http_status"] == 200
                )
                assert row["raw_llm_proposal"] is not None
            assert sum(bool(r.get("llm_reflection")) for r in records) == 8
            assert sum(c["http_status"] == 200 for c in calls) == 21
            assert sum(c["status"] == "not_called" for c in calls) == 4
            assert (
                sum((c.get("usage") or {}).get("total_tokens", 0) for c in calls)
                == 107826
            )
            trace = lines(directory / "graph_trace.jsonl")
            nodes = {r["node"] for r in trace}
            assert len(nodes) == 9
            assert sum(r["node"] == "SkillExecutor" for r in trace) == 12
            terminal = next(
                r["update"] for r in reversed(trace) if r["node"] == "ResearchPlanner"
            )
            assert terminal["actual_planner"] == "DeterministicPlanner"
            assert "budget" in terminal["fallback_reason"]
        data[arm] = {
            "rounds": len(records),
            "all_saved_metrics_recomputed": True,
            "scenarios": scenarios,
            "tools_seconds": total,
        }
    assert sum(r["rounds"] for r in data.values()) == 44
    return {
        "status": "passed",
        "new_api_requests": 0,
        "models_retrained": False,
        "saved_candidates_verified": 44,
        "arms": data,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", default="results/stage7_langgraph/live-study-002")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = (PROJECT_ROOT / args.study).resolve()
    result = verify(root)
    if args.output:
        target = (PROJECT_ROOT / args.output).resolve()
        allowed = PROJECT_ROOT / "results/stage7_langgraph/v1.1.0-audit"
        if not target.is_relative_to(allowed) or target.exists():
            raise ValueError("Output must be a new v1.1.0-audit file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "status": result["status"],
                "new_api_requests": 0,
                "saved_candidates_verified": 44,
            }
        )
    )


if __name__ == "__main__":
    main()
