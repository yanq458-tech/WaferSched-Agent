"""Committed JSON is authoritative; real Semantica memory/graph provide context."""

import csv
import io
import json

from wafer_sched.infrastructure.io import atomic_record
from ..artifacts import _atomic_text
from ._semantica.context.agent_memory import AgentMemory
from ._semantica.context.context_graph import ContextGraph
from .feedback import best_row
from ..infrastructure.paths import resolve_path


class ResearchMemory:
    def __init__(self, root, *, manifest, resume=False):
        self.root = resolve_path(root)
        if resume:
            saved = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
            if saved != manifest:
                raise ValueError("Resume manifest/configuration/model identity differs")
        else:
            self.root.mkdir(parents=True, exist_ok=False)
            atomic_record(self.root / "manifest.json", manifest)
        self.manifest = manifest
        self.history = []
        self.memory = AgentMemory(max_memory_size=10000, short_term_limit=1000, token_limit=100000)
        self.graph = ContextGraph(advanced_analytics=False, extract_entities=False, extract_relationships=False)
        self.calls = {"store": 0, "retrieve": 0, "add_node": 0, "add_edge": 0, "get_neighbors": 0}
        self.graph.add_node(manifest["scenario_id"], "equipment", config_sha256=manifest["config_sha256"])
        self.calls["add_node"] += 1
        for directory in sorted(self.root.glob("round-*")):
            record = directory / "record.json"
            if not record.exists():
                raise ValueError("Uncommitted experiment exists; recovery is supported at experiment boundaries only")
            row = json.loads(record.read_text(encoding="utf-8"))
            if row["round"] != len(self.history) + 1:
                raise ValueError("Committed research history is not contiguous")
            self.history.append(row)
            self._index(row)
        self._publish()

    def _index(self, row):
        proposal = row["proposal"]
        identifier = proposal["experiment_id"]
        summary = {"scenario": proposal["scenario_id"], "experiment_id": identifier,
                   "method": proposal["proposed_method"], "parameters": proposal["parameters"],
                   "metrics": row["result"]["metrics"], "verification": row["result"]["verification"]["valid"],
                   "acceptance": row["acceptance"], "analysis": row["analysis"]}
        self.memory.store(json.dumps(summary, ensure_ascii=False), metadata={"type": "experiment",
                          "scenario_id": proposal["scenario_id"]}, memory_id=identifier)
        self.calls["store"] += 1
        method_id = "method-" + proposal["proposed_method"]
        self.graph.add_node(method_id, "skill", method=proposal["proposed_method"])
        self.graph.add_node(identifier, "experiment", proposal=proposal,
                            verified=row["result"]["verification"]["valid"], acceptance=row["acceptance"])
        self.calls["add_node"] += 2
        self.graph.add_edge(proposal["scenario_id"], identifier, "evaluated_by")
        self.graph.add_edge(identifier, method_id, "invokes")
        self.calls["add_edge"] += 2
        for evidence in proposal["evidence_from_history"]:
            self.graph.add_edge(evidence, identifier, "feedback_evidence")
            self.calls["add_edge"] += 1

    def recall(self):
        query = self.manifest["scenario_id"]
        matches = self.memory.retrieve(query, max_results=max(1, len(self.history)), type="experiment")
        neighbors = self.graph.get_neighbors(query, hops=1)
        self.calls["retrieve"] += 1
        self.calls["get_neighbors"] += 1
        committed = {row["proposal"]["experiment_id"]: row for row in self.history}
        if set(committed) != {item["memory_id"] for item in matches}:
            raise RuntimeError("Semantica retrieved context does not cover committed scenario feedback")
        for item in matches:
            summary = json.loads(item["content"])
            if summary["metrics"] != committed[item["memory_id"]]["result"]["metrics"]:
                raise RuntimeError("Semantica summary differs from authoritative event metrics")
        return {"memory_ids": [item["memory_id"] for item in matches],
                "graph_neighbor_count": len(neighbors), "source": "real_semantica_local_source_subset"}

    def recalled_history(self, recall):
        ids = set(recall["memory_ids"])
        return [row for row in self.history if row["proposal"]["experiment_id"] in ids]

    def commit(self, row):
        if row["round"] != len(self.history) + 1:
            raise ValueError("Commit is out of order")
        directory = self.root / row["proposal"]["experiment_id"]
        atomic_record(directory / "record.json", row)
        self.history.append(row)
        self._index(row)
        self._publish()

    def record_plan(self, decision):
        payload = {"proposal": decision.proposal.to_dict() if decision.proposal else None,
                   "reason": decision.reason, "actual_planner": decision.actual_planner,
                   "fallback_reason": decision.fallback_reason}
        if self.history:
            self.history[-1]["next_plan"] = payload
            atomic_record(self.root / self.history[-1]["proposal"]["experiment_id"] / "record.json", self.history[-1])
        atomic_record(self.root / "next_plan.json", payload)
        self._publish()

    def finish(self, reason):
        best = best_row(self.history)
        spans = [row["result"]["metrics"]["makespan_seconds"] for row in self.history
                 if row["result"]["verification"]["valid"]]
        best_span = min(spans) if spans else None
        time_to_best = next((row["elapsed_seconds"] for row in self.history
                            if row["result"]["verification"]["valid"] and
                            row["result"]["metrics"]["makespan_seconds"] == best_span), None)
        summary = {"stop_reason": reason, "rounds": len(self.history), "best_makespan_seconds": best_span,
                   "best_experiment_id": best["proposal"]["experiment_id"] if best else None,
                   "best_proposal": best["proposal"] if best else None, "time_to_best_seconds": time_to_best,
                   "elapsed_seconds": self.history[-1]["elapsed_seconds"] if self.history else 0,
                   "constraint_pass_rate": sum(row["result"]["verification"]["valid"] for row in self.history) / len(self.history)
                   if self.history else None, "semantica_calls": self.calls}
        atomic_record(self.root / "summary.json", summary)
        self._publish()
        return summary

    def _publish(self):
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.history)
        _atomic_text(self.root / "experiments.jsonl", text)
        stream = io.StringIO(newline="")
        fields = ["round", "experiment_id", "scenario_id", "method", "parameters", "planner", "fallback_reason",
                  "seed", "config_sha256", "verified", "completed_wafers", "makespan_seconds", "wph",
                  "mean_chamber_utilization", "robot_utilization", "average_waiting_seconds", "blocking_seconds",
                  "wall_seconds", "elapsed_seconds", "accepted", "acceptance_reason", "best_so_far_seconds",
                  "solver_status", "solver_bound_seconds", "solver_seconds", "selection_reason", "evidence"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in self.history:
            proposal, result = row["proposal"], row["result"]
            metrics, solver = result["metrics"], result.get("solver") or {}
            writer.writerow({"round": row["round"], "experiment_id": proposal["experiment_id"],
                "scenario_id": proposal["scenario_id"], "method": proposal["proposed_method"],
                "parameters": json.dumps(proposal["parameters"], sort_keys=True), "planner": row["actual_planner"],
                "fallback_reason": row["fallback_reason"], "seed": result["seed"],
                "config_sha256": result["config_sha256"], "verified": result["verification"]["valid"],
                "completed_wafers": metrics.get("completed_wafers"), "makespan_seconds": metrics.get("makespan_seconds"),
                "wph": metrics.get("finite_batch_wph"), "mean_chamber_utilization": metrics.get("mean_chamber_utilization"),
                "robot_utilization": metrics.get("robot_utilization"), "average_waiting_seconds": metrics.get("average_waiting_seconds"),
                "blocking_seconds": metrics.get("blocking_seconds"), "wall_seconds": result["wall_seconds"],
                "elapsed_seconds": row["elapsed_seconds"], "accepted": row["acceptance"]["accepted"],
                "acceptance_reason": row["acceptance"]["reason"], "best_so_far_seconds": row["best_so_far_seconds"],
                "solver_status": solver.get("status"), "solver_bound_seconds": solver.get("best_bound_seconds"),
                "solver_seconds": solver.get("solver_seconds"), "selection_reason": proposal["selection_reason"],
                "evidence": json.dumps(proposal["evidence_from_history"])})
        _atomic_text(self.root / "decisions.csv", stream.getvalue())
        atomic_record(self.root / "context_graph.json", self.graph.to_dict())
        atomic_record(self.root / "semantica_calls.json", self.calls)
        # Original upstream save is exercised; authoritative records remain atomic JSON.
        self.memory.save(str(self.root / "semantica_memory"))
