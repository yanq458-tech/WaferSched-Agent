"""Predeclared ablations and one-shot holdout evaluation, with no test-to-planner edge."""

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
from statistics import mean

from wafer_sched.infrastructure.io import atomic_record
from ..artifacts import PROJECT_ROOT, _atomic_text
from ..infrastructure.paths import resolve_path, relative_path
from .cli import run_study
from .experiment_runner import ExperimentRunner, ResearchLimits, source_hashes
from .planner import FixedOrderPlanner


def read_history(directory):
    return [json.loads(line) for line in (Path(directory) / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]


def write_csv(path, rows):
    stream = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
                         for key, value in row.items()})
    _atomic_text(Path(path), stream.getvalue())


class StageSixEvaluation:
    def __init__(self, study_path, root):
        self.study_path, self.root = resolve_path(study_path), resolve_path(root)
        self.study = json.loads(self.study_path.read_text(encoding="utf-8"))
        self.root.mkdir(parents=True, exist_ok=True)

    def declare(self):
        seal_path = PROJECT_ROOT / "configs/wafer_sched/agent/holdout_seal.json"
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        for row in self.study["holdout"]:
            if hashlib.sha256((PROJECT_ROOT / row["config"]).read_bytes()).hexdigest() != seal[row["name"]]["sha256"]:
                raise ValueError("Sealed test equipment changed")
        protocol = {"declared_at_utc": datetime.now(timezone.utc).isoformat(), "study": self.study,
                    "holdout_seal": seal, "source_sha256": source_hashes(),
                    "holdout_references": [("rule", {"policy": name}) for name in self.study["candidates"]["rules"]]
                    + [("rl", {"model_id": name}) for name in self.study["candidates"]["models"]]
                    + [("cpsat", {"max_seconds": b}) for b in [1, 3]],
                    "holdout_assignment": {self.study["holdout"][0]["name"]: self.study["development"][0]["name"],
                                           self.study["holdout"][1]["name"]: self.study["development"][1]["name"]},
                    "fairness": "same candidate set, 80s total cap and 8 calls per ablation; measured actual time may differ",
                    "solver_seed_semantics": "static equipment; solver search seeds are not random disturbance repetitions"}
        path = self.root / "protocol_before_development.json"
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            for key in ("study", "holdout_seal", "source_sha256", "holdout_references", "holdout_assignment"):
                if json.loads(json.dumps(saved[key])) != json.loads(json.dumps(protocol[key])):
                    raise ValueError("Declared study changed; choose a fresh output directory")
            return saved
        if list(self.root.glob("development/*/*/summary.json")):
            raise ValueError("Cannot declare protocol retrospectively")
        atomic_record(path, protocol)
        return protocol

    def development(self):
        self.declare()
        for scenario in self.study["development"]:
            for seed in self.study["solver_seeds"]:
                for planner in ("fixed", "deterministic"):
                    directory = self.root / "development" / scenario["name"] / f"{planner}-seed-{seed}"
                    if directory.exists():
                        raise FileExistsError("Completed/partial studies are preserved; use a new root for reruns")
                    run_study(self.study, scenario, planner, directory, seed=seed)
        configured = all(os.environ.get(key) for key in (
            "ASSISTANT_LLM_BASE_URL", "ASSISTANT_LLM_API_KEY", "ASSISTANT_LLM_MODEL"))
        authorized = self.study.get("allow_llm_egress", False)
        atomic_record(self.root / "llm_availability.json", {"configured": configured, "research_egress_enabled": authorized,
                      "actual_llm_comparison_run": bool(configured and authorized),
                      "fallback_is_not_llm_evidence": True})
        if configured and authorized:
            for scenario in self.study["development"]:
                for seed in self.study["solver_seeds"]:
                    run_study(self.study, scenario, "llm", self.root / "development" / scenario["name"] / f"llm-seed-{seed}", seed=seed)
        else:
            # Real fallback invocation, excluded from the LLM performance ablation.
            reduced = {**self.study, "limits": {**self.study["limits"], "max_rounds": 1}}
            run_study(reduced, self.study["development"][0], "llm", self.root / "llm-fallback-check")
        self.aggregate()

    def budgets(self):
        self.declare()
        for scenario in self.study["development"]:
            for budget in self.study["candidates"]["cp_budgets"]:
                order = [("rule", {"policy": "fifo"}), ("cpsat", {"max_seconds": budget})]
                ExperimentRunner().run(config_path=scenario["config"], scenario_id=scenario["name"],
                    window_seconds=scenario["window_seconds"], planner=FixedOrderPlanner(order),
                    output_root=self.root / "budgets" / scenario["name"] / f"fixed-{budget}",
                    candidates=self.study["candidates"], seed=0,
                    limits=ResearchLimits(max_rounds=2, total_seconds=80, max_experiment_seconds=40))
            run_study(self.study, scenario, "cp_adaptive", self.root / "budgets" / scenario["name"] / "adaptive")
        self.aggregate()

    def freeze(self):
        self.declare()
        if (self.root / "frozen_method.json").exists():
            raise FileExistsError("Method already frozen; no repeated test-guided selection")
        chosen = {}
        for scenario in self.study["development"]:
            configurations = defaultdict(lambda: defaultdict(list))
            for directory in (self.root / "development" / scenario["name"]).glob("*-seed-*"):
                if directory.name.startswith("llm-"):
                    continue
                seed = int(directory.name.rsplit("-", 1)[-1])
                for row in read_history(directory):
                    if row["result"]["verification"]["valid"]:
                        key = json.dumps([row["proposal"]["proposed_method"], row["proposal"]["parameters"]], sort_keys=True)
                        configurations[key][seed].append(row)
            eligible = []
            for key, by_seed in configurations.items():
                if set(by_seed) != set(self.study["solver_seeds"]):
                    continue
                records = [min(by_seed[s], key=lambda r: (r["result"]["metrics"]["makespan_seconds"],
                            r["result"]["wall_seconds"])) for s in self.study["solver_seeds"]]
                eligible.append((mean(r["result"]["metrics"]["makespan_seconds"] for r in records),
                                 mean(r["result"]["wall_seconds"] for r in records), key, records))
            if not eligible:
                raise ValueError("No method has verified evidence for every predeclared development seed")
            span, cost, key, records = min(eligible, key=lambda entry: entry[:3])
            method, parameters = json.loads(key)
            chosen[scenario["name"]] = {"method": method, "parameters": parameters,
                "development_mean_makespan_seconds": span, "development_mean_wall_seconds": cost,
                "source_experiments": [relative_path(resolve_path(r["result"]["artifact_directory"]).parent) for r in records]}
        atomic_record(self.root / "frozen_method.json", {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "selection_data": "development_only", "selection": chosen, "source_sha256": source_hashes(),
            "test_metrics_used": False, "training_performed": False})
        return chosen

    def holdout(self):
        protocol = self.declare()
        frozen_path = self.root / "frozen_method.json"
        if not frozen_path.exists():
            raise ValueError("Freeze development-selected methods before test evaluation")
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        if frozen["source_sha256"] != source_hashes():
            raise ValueError("Planner/tool code changed after method freezing")
        atomic_record(self.root / "holdout_protocol_at_start.json", {
            "frozen_method_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
            "sealed_hashes": protocol["holdout_seal"], "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "no_test_feedback_to_planner": True})
        labels = {}
        for scenario in self.study["holdout"]:
            dev = protocol["holdout_assignment"][scenario["name"]]
            selection = frozen["selection"][dev]
            references = [(m, p) for m, p in protocol["holdout_references"]]
            target = (selection["method"], selection["parameters"])
            if target not in references:
                references.append(target)
            for method, parameters in references:
                identifier = (parameters.get("policy") or parameters.get("model_id")
                              or f"cp-{parameters['max_seconds']}")
                directory = self.root / "holdout" / scenario["name"] / identifier
                summary = ExperimentRunner().run(config_path=scenario["config"], scenario_id=scenario["name"],
                    window_seconds=scenario["window_seconds"], planner=FixedOrderPlanner([(method, parameters)]),
                    output_root=directory, candidates=self.study["candidates"], seed=0,
                    limits=ResearchLimits(max_rounds=1, total_seconds=80, max_experiment_seconds=40))
                labels[str(directory.relative_to(self.root))] = {"frozen_cfar_choice": (method, parameters) == target,
                    "development_source": dev, "best_seconds": summary["best_makespan_seconds"],
                    "one_shot_reference": True}
        atomic_record(self.root / "holdout_labels.json", labels)
        self.aggregate()

    def aggregate(self):
        rows, summaries, raw = [], [], []
        for directory in sorted(self.root.rglob("summary.json")):
            if "smoke" in directory.parts:
                continue
            study_directory = directory.parent
            if not (study_directory / "manifest.json").exists():
                continue
            label = study_directory.relative_to(self.root).as_posix()
            summary = json.loads(directory.read_text(encoding="utf-8"))
            manifest = json.loads((study_directory / "manifest.json").read_text(encoding="utf-8"))
            summaries.append({"study": label, "scenario": manifest["scenario_id"], "seed": manifest["seed"],
                "planner": manifest["requested_planner"], "best_makespan_seconds": summary["best_makespan_seconds"],
                "time_to_best_seconds": summary["time_to_best_seconds"], "elapsed_seconds": summary["elapsed_seconds"],
                "total_session_wall_seconds": summary.get("total_session_wall_seconds"),
                "calls": summary["rounds"], "constraint_pass_rate": summary["constraint_pass_rate"],
                "stop_reason": summary["stop_reason"]})
            for row in read_history(study_directory):
                result, proposal = row["result"], row["proposal"]
                raw.append({"study": label, **row})
                rows.append({"study": label, "scenario": proposal["scenario_id"], "round": row["round"],
                    "method": proposal["proposed_method"], "parameters": proposal["parameters"],
                    "actual_planner": row["actual_planner"], "seed": result["seed"],
                    "config_sha256": result["config_sha256"], "window_seconds": result["window_seconds"],
                    "verified": result["verification"]["valid"], **result["metrics"],
                    "wall_seconds": result["wall_seconds"], "elapsed_seconds": row["elapsed_seconds"],
                    "accepted": row["acceptance"]["accepted"], "reason": row["acceptance"]["reason"],
                    "best_so_far_seconds": row["best_so_far_seconds"],
                    "solver_status": (result.get("solver") or {}).get("status"),
                    "solver_bound_seconds": (result.get("solver") or {}).get("best_bound_seconds"),
                    "solver_seconds": (result.get("solver") or {}).get("solver_seconds"),
                    "selection_reason": proposal["selection_reason"], "evidence": proposal["evidence_from_history"],
                    "fallback_reason": row["fallback_reason"]})
        write_csv(self.root / "comparison.csv", summaries)
        write_csv(self.root / "decisions.csv", rows)
        _atomic_text(self.root / "experiments.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in raw))
        return raw, summaries
