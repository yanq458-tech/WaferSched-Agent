"""Bounded CFAR loop, using the platform's callable scheduler and atomic records."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys
from time import perf_counter

from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.scheduler import WorkspaceRunScheduler
from ..artifacts import PROJECT_ROOT
from ..config import load_config
from ..infrastructure.paths import resolve_path, relative_path
from .feedback import FeedbackEvaluator, best_record
from .planner import PlanningDecision
from .research_memory import ResearchMemory
from .schemas import config_hash, positive
from .skills import SkillRegistry, model_compatibility


@dataclass(frozen=True)
class ResearchLimits:
    max_rounds: int = 8
    total_seconds: float = 80.0
    max_experiment_seconds: float = 40.0
    max_decisions: int = 4096

    def __post_init__(self):
        for key in ("max_rounds", "max_decisions"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"Invalid {key}")
        positive(self.total_seconds, "total_seconds")
        positive(self.max_experiment_seconds, "max_experiment_seconds")


def source_hashes():
    root = PROJECT_ROOT / "src/wafer_sched"
    return {p.relative_to(PROJECT_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*.py"))}


def candidate_catalogue(config, rules, cp_budgets, models):
    from ..policies.rules import POLICIES
    if not rules or len(set(rules)) != len(rules) or not set(rules) <= set(POLICIES):
        raise ValueError("Invalid rule candidate list")
    if not cp_budgets or len(set(cp_budgets)) != len(cp_budgets):
        raise ValueError("Invalid CP budget list")
    for budget in cp_budgets:
        positive(budget, "cp_budget")
        if budget > 30:
            raise ValueError("Single solver search budget may not exceed 30 seconds")
    compatible, rejected = {}, {}
    for identifier, model in models.items():
        path = (PROJECT_ROOT / model["path"]).resolve()
        if not path.is_relative_to(PROJECT_ROOT / "results/wafer_sched/stage5/training") or path.suffix != ".zip":
            raise ValueError("RL catalogue must point to read-only stage-five trained models")
        specification = {**model, "path": relative_path(path)}
        try:
            model_compatibility(config, specification)
            specification["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            specification["metadata_sha256"] = hashlib.sha256((path.parent / "metadata.json").read_bytes()).hexdigest()
            compatible[identifier] = specification
        except (ValueError, FileNotFoundError) as exc:
            rejected[identifier] = {"error_type": type(exc).__name__, "status": "not_compatible_not_executed"}
    return {"rules": list(rules), "cp_budgets": list(cp_budgets), "models": compatible}, rejected


class ExperimentRunner:
    def run(self, *, config_path, scenario_id, window_seconds, planner, output_root, candidates,
            seed=0, limits=ResearchLimits(), resume=False, pause_after=None):
        if type(seed) is not int or seed < 0:
            raise ValueError("Seed must be a nonnegative integer")
        positive(window_seconds, "window_seconds")
        if pause_after is not None and (type(pause_after) is not int or pause_after < 1):
            raise ValueError("pause_after must be a positive round boundary")
        started = perf_counter()
        config_path = resolve_path(config_path)
        output_root = resolve_path(output_root)
        config = load_config(config_path)
        effective, incompatible = candidate_catalogue(config, **candidates)
        manifest = {"scenario_id": scenario_id, "config_sha256": config_hash(config),
                    "config": config.to_dict(), "config_path": relative_path(config_path), "window_seconds": window_seconds,
                    "seed": seed, "limits": asdict(limits), "candidate_catalogue": effective,
                    "incompatible_models": incompatible, "requested_planner": planner.name,
                    "fixed_order": getattr(planner, "order", None),
                    "allow_llm_egress": getattr(planner, "allow_llm_egress", False),
                    "source_sha256": source_hashes(), "new_rl_training_enabled": False}
        # Normalize tuples to the exact persisted JSON shape.
        manifest = json.loads(json.dumps(manifest))
        memory = ResearchMemory(output_root, manifest=manifest, resume=resume)
        registry, evaluator = SkillRegistry(), FeedbackEvaluator()
        prior_elapsed = memory.history[-1]["elapsed_seconds"] if memory.history else 0.0
        if resume and (memory.root / "summary.json").exists():
            prior = json.loads((memory.root / "summary.json").read_text(encoding="utf-8"))
            if prior["stop_reason"] != "paused_at_experiment_boundary":
                return prior
        scheduler = WorkspaceRunScheduler(max_workers=1, max_pending_per_workspace=1, queue_timeout=5)
        try:
            while True:
                elapsed = prior_elapsed + perf_counter() - started
                remaining = limits.total_seconds - elapsed
                if len(memory.history) >= limits.max_rounds:
                    decision = PlanningDecision(None, "max_rounds", planner.name)
                elif remaining <= 0:
                    decision = PlanningDecision(None, "total_wall_budget_exhausted", planner.name)
                else:
                    analysis = registry.invoke("ProblemAnalysisSkill", config, memory.history, effective)
                    recalled = memory.recall()
                    # Value-only history copies prevent a planner mutating committed records.
                    decision = registry.invoke("ResearchPlanningSkill", planner, scenario_id=scenario_id,
                        history=json.loads(json.dumps(memory.recalled_history(recalled))), analysis=analysis, candidates=effective,
                        remaining=remaining, max_experiment_seconds=limits.max_experiment_seconds,
                        recalled_memories=recalled)
                memory.record_plan(decision)
                if decision.proposal is None:
                    summary = memory.finish(decision.reason)
                    summary["total_session_wall_seconds"] = prior_elapsed + perf_counter() - started
                    summary["budget_seconds"] = limits.total_seconds
                    atomic_record(memory.root / "summary.json", summary)
                    return summary
                proposal = decision.proposal
                # Planning cost counts toward budget: recompute admission just before dispatch.
                remaining = limits.total_seconds - prior_elapsed - (perf_counter() - started)
                if proposal.estimated_budget > min(remaining, limits.max_experiment_seconds):
                    memory.record_plan(PlanningDecision(None, "remaining_budget_changed_during_planning", decision.actual_planner))
                    return memory.finish("remaining_budget_changed_during_planning")
                proposal.validate_context(scenario_id, memory.history, effective, remaining, limits.max_experiment_seconds)
                directory = memory.root / proposal.experiment_id
                directory.mkdir(exist_ok=False)
                incumbent = best_record(memory.history)
                context = {"config_path": relative_path(config_path), "seed": seed, "window_seconds": window_seconds,
                    "experiment_directory": relative_path(directory), "models": effective["models"],
                    "max_decisions": limits.max_decisions,
                    "incumbent_directory": incumbent["artifact_directory"] if incumbent else None}
                request = {"proposal": proposal.to_dict(), "context": context}
                atomic_record(directory / "input.json", {"proposal": proposal.to_dict(), "config": config.to_dict(),
                              "seed": seed, "source_sha256": manifest["source_sha256"]})
                deadline = min(remaining, limits.max_experiment_seconds)
                begin = perf_counter()
                def dispatch():
                    # Fixed executable/module only. Proposal never contributes command text.
                    return subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/run_worker.py")],
                        input=json.dumps(request).encode("utf-8"), stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, timeout=deadline, cwd=PROJECT_ROOT, check=False)
                worker_error = None
                try:
                    completed = scheduler.submit("wafer-research-" + scenario_id, dispatch).result()
                    if completed.returncode != 0:
                        worker_error = "worker_failed"
                except subprocess.TimeoutExpired:
                    worker_error = "single_experiment_wall_timeout"
                wall = perf_counter() - begin
                if worker_error is None:
                    result = json.loads((directory / "worker_result.json").read_text(encoding="utf-8"))
                else:
                    failure = directory / "worker_failure.json"
                    details = json.loads(failure.read_text(encoding="utf-8")) if failure.exists() else {}
                    # No invented metrics for a failed/uncompleted numerical attempt.
                    result = {"scenario_id": scenario_id, "config_sha256": config_hash(config),
                        "window_seconds": window_seconds, "seed": seed, "status": worker_error,
                        "metrics": {}, "solver": None, "model": None, "artifact_directory": None,
                        "skill_calls": [], "failure": details,
                        "verification": {"valid": False, "complete": False, "issues": [worker_error],
                                         "constraint_violations": None, "deadlock_count": None}}
                result["wall_seconds"] = wall
                acceptance = evaluator.evaluate(result, incumbent)
                analysis_result = registry.invoke("ExperimentAnalysisSkill", result, incumbent)
                best_span = (result["metrics"].get("makespan_seconds") if acceptance["accepted"]
                             else incumbent["metrics"]["makespan_seconds"] if incumbent else None)
                row = {"round": len(memory.history) + 1, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                       "proposal": proposal.to_dict(), "actual_planner": decision.actual_planner,
                       "fallback_reason": decision.fallback_reason, "observed_analysis": analysis,
                       "semantica_recall": recalled, "result": result, "acceptance": acceptance,
                       "analysis": analysis_result, "best_so_far_seconds": best_span,
                       "elapsed_seconds": prior_elapsed + perf_counter() - started, "next_plan": None,
                       "control_skill_calls": registry.calls[-3:]}
                memory.commit(row)
                print(f"{scenario_id}/{planner.name} round {row['round']}: {proposal.proposed_method} "
                      f"{proposal.parameters} status={result['status']} verified={result['verification']['valid']} "
                      f"makespan={result['metrics'].get('makespan_seconds')} acceptance={acceptance['reason']}", flush=True)
                if pause_after and len(memory.history) >= pause_after:
                    return memory.finish("paused_at_experiment_boundary")
        finally:
            scheduler.shutdown()
