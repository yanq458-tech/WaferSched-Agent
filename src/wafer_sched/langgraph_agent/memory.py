"""One preserved ResearchMemory per instance plus ordered graph session records."""

import json
from pathlib import Path

from wafer_sched.agent.experiment_runner import source_hashes
from wafer_sched.agent.research_memory import ResearchMemory
from wafer_sched.agent.schemas import config_hash
from wafer_sched.artifacts import _atomic_text
from wafer_sched.config import load_config
from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.paths import PROJECT_ROOT, resolve_path


class SessionMemory:
    def __init__(self, root, study, candidates, mode, public_llm, seed, resume=False):
        self.root = Path(root).resolve()
        permitted = [
            PROJECT_ROOT / "results/stage7_langgraph",
            PROJECT_ROOT / "results/local",
        ]
        if not any(
            self.root.is_relative_to(p.resolve()) and self.root != p.resolve()
            for p in permitted
        ):
            raise ValueError(
                "Output must be a new directory below results/stage7_langgraph or results/local"
            )
        manifest = json.loads(
            json.dumps(
                {
                    "study": study,
                    "mode": mode,
                    "seed": seed,
                    "candidates": candidates,
                    "llm": public_llm if mode == "llm" else None,
                    "source_sha256": source_hashes(),
                    "graph_framework": "LangGraph",
                    "new_rl_training_enabled": False,
                }
            )
        )
        if resume:
            saved = json.loads(
                (self.root / "manifest.json").read_text(encoding="utf-8")
            )
            if saved != manifest:
                raise ValueError(
                    "Resume manifest/configuration/model/source identity differs"
                )
        else:
            self.root.mkdir(parents=True, exist_ok=False)
            atomic_record(self.root / "manifest.json", manifest)
        self.histories = {}
        self.records = []
        for scenario in study["development"]:
            config = load_config(resolve_path(scenario["config"]))
            local_manifest = {
                "scenario_id": scenario["name"],
                "config_sha256": config_hash(config),
                "parent_manifest": manifest,
                "window_seconds": scenario["window_seconds"],
            }
            self.histories[scenario["name"]] = ResearchMemory(
                self.root / "scenarios" / scenario["name"],
                manifest=local_manifest,
                resume=resume,
            )
            self.records.extend(self.histories[scenario["name"]].history)
        self.records.sort(key=lambda r: r["global_round"])
        if [r["global_round"] for r in self.records] != list(
            range(1, len(self.records) + 1)
        ):
            raise ValueError("Noncontiguous global research history")

    def histories_as_values(self):
        return {k: json.loads(json.dumps(m.history)) for k, m in self.histories.items()}

    def record_next_plan(self, decision):
        if self.records:
            row = self.records[-1]
            row["next_plan"] = decision
            atomic_record(
                self.histories[row["proposal"]["scenario_id"]].root
                / row["proposal"]["experiment_id"]
                / "record.json",
                row,
            )
            self.publish()
        atomic_record(self.root / "next_plan.json", decision)

    def commit(self, row):
        existing = [
            r
            for r in self.records
            if r["proposal"]["experiment_id"] == row["proposal"]["experiment_id"]
        ]
        if existing:
            if existing[0] != row:
                raise ValueError("Conflicting repeated experiment commit")
            return
        if row["global_round"] != len(self.records) + 1:
            raise ValueError("Global experiment commit out of order")
        local = self.histories[row["proposal"]["scenario_id"]]
        row["round"] = len(local.history) + 1
        local.commit(row)
        self.records.append(row)
        self.publish()

    def publish(self):
        _atomic_text(
            self.root / "experiments.jsonl",
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.records),
        )
