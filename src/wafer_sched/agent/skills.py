"""Executable Skills wrap original tools; they never implement device transitions."""

from dataclasses import dataclass
import hashlib
import json
from time import perf_counter

from wafer_sched.infrastructure.io import atomic_record
from ..actions import Action
from ..artifacts import _atomic_text, save_run
from ..config import load_config
from ..infrastructure.paths import resolve_path, relative_path
from ..metrics import calculate_metrics
from ..observation import ObservationBuilder
from ..policies.rules import make_policy
from ..policy_runner import run_policy
from ..simulator import Simulator
from .feedback import best_record
from .schemas import ExperimentProposal, config_hash


def replay_decisions(config, decisions, window, seed=0):
    sim = Simulator(config, seed=seed)
    for row in decisions:
        if row["time"] < sim.state.time - 1e-7 or row["time"] > window:
            raise ValueError("Replay decision time outside the observation window")
        sim.run_until(max(row["time"], sim.state.time))
        action = Action(**row["action"])
        if not sim.validate_action(action) or not sim.submit(action):
            raise ValueError("Original action checker rejected saved decision")
    sim.run_until(window)
    if not sim.validate_state():
        raise ValueError("Original state checker rejected replay")
    return sim


class ProblemAnalysisSkill:
    name = "ProblemAnalysisSkill"

    def run(self, config, history, candidates):
        # Known static recipes, not simulator's hidden event queue.
        loads = {c.chamber_id: 0.0 for c in config.chambers}
        times = {c.chamber_id: dict(c.processing_times) for c in config.chambers}
        for wafer in config.wafers:
            for step in wafer.route:
                duration = min(times[c][step.recipe] for c in step.chambers)
                for c in step.chambers:
                    loads[c] += duration / len(step.chambers)
        incumbent = best_record(history)
        metrics = incumbent["metrics"] if incumbent else {}
        span = metrics.get("makespan_seconds")
        processing = sum(metrics.get("chamber_processing_seconds", {}).values())
        block_ratio = metrics.get("blocking_seconds", 0) / max(processing, 1e-9)
        busy_ratio = metrics.get("robot_action_seconds", 0) / span if span else None
        cp_history = [row for row in history if row["proposal"]["proposed_method"] == "cpsat"]
        last_solver = (cp_history[-1]["result"].get("solver") or {}) if cp_history else {}
        previous_limit = cp_history[-1]["proposal"]["parameters"]["max_seconds"] if cp_history else 0
        proven = any((row["result"].get("solver") or {}).get("status") == "OPTIMAL"
                     and row["result"]["verification"]["valid"]
                     and not (row["result"].get("solver") or {}).get("restricted_model", True) for row in cp_history)
        next_limit = next((b for b in sorted(candidates["cp_budgets"]) if b > previous_limit), None) if not proven else None
        return {"objective": "verified_complete_batch_makespan_then_wall_cost",
                "nominal_minimum_load_by_chamber": loads,
                "nominal_bottleneck": max(loads, key=loads.get),
                "blocking_to_processing_ratio": block_ratio,
                "completion_window_robot_utilization": busy_ratio,
                "historical_failure_count": sum(not row["result"]["verification"]["valid"] for row in history),
                "available_methods": {"rule": list(candidates["rules"]),
                                      "cpsat": list(candidates["cp_budgets"]),
                                      "rl": list(candidates["models"])},
                "budget_advice": {"next_untried_cp_search_seconds": next_limit,
                    "estimated_cp_experiment_seconds": next_limit + 3 if next_limit else None,
                    "estimated_pretrained_rl_experiment_seconds": 10.0 if candidates["models"] else None,
                    "requires_remaining_wall_budget_admission": True,
                    "reason": "verified optimum: no further CP proof budget" if proven else
                              f"untried CP budget after status={last_solver.get('status')}; planner may prefer a cheaper Skill",
                    "estimates_are_not_measured_cost": True},
                "current_best_seconds": span, "scope": "static_known_recipe_analysis"}


@dataclass
class NumericalOutcome:
    simulator: object
    outcome: dict
    decisions: list
    solver: dict | None = None
    model: dict | None = None
    cp_verification: dict | None = None


class RuleSchedulingSkill:
    name = "RuleSchedulingSkill"

    def run(self, config, parameters, context):
        sim = Simulator(config, seed=context["seed"])
        run = run_policy(sim, make_policy(parameters["policy"]), max_time=context["window_seconds"],
                         max_steps=context["max_decisions"])
        return NumericalOutcome(sim, run.outcome, run.decisions)


class CPSATOptimizationSkill:
    name = "CPSATOptimizationSkill"

    def run(self, config, parameters, context):
        from ..cpsat_solver import SolverOptions, solve_schedule
        from ..cpsat_validator import validate_solution
        incumbent = None
        if context.get("incumbent_directory"):
            directory = resolve_path(context["incumbent_directory"])
            incumbent_config = load_config(directory / "config.json")
            if config_hash(incumbent_config) != config_hash(config):
                raise ValueError("Hint belongs to another equipment instance")
            decisions = json.loads((directory / "decisions.json").read_text(encoding="utf-8"))["decisions"]
            incumbent = replay_decisions(config, decisions, context["window_seconds"], context["seed"])
            if not incumbent.completed:
                raise ValueError("Incomplete hint rejected")
        result = solve_schedule(config, SolverOptions(max_seconds=parameters["max_seconds"],
                                seed=context["seed"], workers=1), incumbent=incumbent)
        atomic_record(resolve_path(context["experiment_directory"]) / "solver.json", result.metadata)
        _atomic_text(resolve_path(context["experiment_directory"]) / "solver.log", result.log)
        if result.schedule is not None:
            atomic_record(resolve_path(context["experiment_directory"]) / "schedule.json", result.schedule)
        replay, verification = validate_solution(config, result, seed=context["seed"])
        sim = replay.simulator if replay else Simulator(config, seed=context["seed"])
        outcome = {"status": "completed" if verification["valid"] else "solver_no_verified_plan",
                   "constraint_violations": verification.get("constraint_violations", 0),
                   "policy": "cpsat", "driver": "original_cp_replay"}
        return NumericalOutcome(sim, outcome, replay.decisions if replay else [], result.metadata,
                                cp_verification=verification)


def model_compatibility(config, model):
    # Reuse exactly the stage-five scope/encoder validation, before loading weights.
    from ..rl.encoding import EncodingSchema, ObservationEncoder
    from ..rl.environment import validate_static_config
    metadata_path = resolve_path(model["path"]).parent / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    schema = EncodingSchema(**metadata["schema"])
    validate_static_config(config, schema)
    ObservationEncoder(schema).encode(ObservationBuilder().build(Simulator(config)))
    if not resolve_path(model["path"]).is_file():
        raise ValueError("Registered pretrained weights are missing")
    return schema


class RLPolicySkill:
    name = "RLPolicySkill"

    def run(self, config, parameters, context):
        import torch
        from ..rl.policy import TrainedPolicyAdapter
        torch.set_num_threads(1)
        identifier = parameters["model_id"]
        model = context["models"][identifier]
        model_compatibility(config, model)
        path = resolve_path(model["path"])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        policy = TrainedPolicyAdapter.load(path)
        sim = Simulator(config, seed=context["seed"])
        run = run_policy(sim, policy, max_time=context["window_seconds"], max_steps=context["max_decisions"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise RuntimeError("Read-only pretrained model changed")
        return NumericalOutcome(sim, run.outcome, run.decisions,
                                model={"model_id": identifier, "path": relative_path(path), "sha256": before,
                                       "training_seed": model["training_seed"], "retrained": False})


class VerificationSkill:
    name = "VerificationSkill"

    def run(self, config, numerical, context):
        sim = numerical.simulator
        issues = []
        window = context["window_seconds"]
        if sim.state.time > window + 1e-7:
            issues.append("candidate_exceeds_predeclared_window")
        else:
            sim.run_until(window)
        complete = sim.completed
        state_valid = bool(sim.validate_state())
        metrics = calculate_metrics(sim.trace)
        replay_valid = False
        if complete:
            try:
                replica = replay_decisions(config, numerical.decisions, window, context["seed"])
                replay_valid = replica.completed and calculate_metrics(replica.trace) == metrics
                if not replay_valid:
                    issues.append("independent_replay_metric_mismatch")
            except (ValueError, RuntimeError, AssertionError) as exc:
                issues.append("independent_replay_" + type(exc).__name__)
        deadlocks = sum(row["event"] == "PotentialDeadlock" for row in sim.trace)
        violations = numerical.outcome.get("constraint_violations", 0)
        if numerical.cp_verification is not None and not numerical.cp_verification["valid"]:
            issues.append("cp_prediction_replay_failed_or_missing")
        valid = (complete and state_valid and replay_valid and not issues and not violations and not deadlocks
                 and numerical.outcome["status"] == "completed")
        return {"valid": bool(valid), "complete": complete, "state_valid": state_valid,
                "independent_replay_valid": replay_valid, "constraint_violations": violations,
                "deadlock_count": deadlocks, "issues": issues,
                "cp_verification": numerical.cp_verification, "metrics_source": "original_event_integrals"}, metrics


class ExperimentAnalysisSkill:
    name = "ExperimentAnalysisSkill"

    def run(self, result, incumbent):
        comparable = incumbent is not None and (result["config_sha256"], result["window_seconds"]) == (
            incumbent["config_sha256"], incumbent["window_seconds"])
        left, right = result["metrics"], incumbent["metrics"] if comparable else {}
        def delta(key):
            return left[key] - right[key] if left.get(key) is not None and right.get(key) is not None else None
        return {"comparable_with_incumbent": comparable,
                "makespan_delta_seconds": delta("makespan_seconds"),
                "blocking_delta_seconds": delta("blocking_seconds"),
                "utilization_delta": delta("mean_chamber_utilization"),
                "candidate_failure": not result["verification"]["valid"],
                "cost_ratio_to_incumbent": result["wall_seconds"] / max(incumbent["wall_seconds"], 1e-9) if comparable else None,
                "solver_status": result.get("solver", {}).get("status") if result.get("solver") else None,
                "generalization_claim": "requires_frozen_independent_test"}


class ResearchPlanningSkill:
    name = "ResearchPlanningSkill"

    def run(self, planner, **context):
        return planner.propose(**context)


class SkillRegistry:
    def __init__(self):
        self.skills = {skill.name: skill for skill in (ProblemAnalysisSkill(), RuleSchedulingSkill(),
                      CPSATOptimizationSkill(), RLPolicySkill(), VerificationSkill(),
                      ExperimentAnalysisSkill(), ResearchPlanningSkill())}
        self.calls = []

    def invoke(self, name, *args, **kwargs):
        if name not in self.skills:
            raise ValueError("Unknown Skill")
        start = perf_counter()
        try:
            output = self.skills[name].run(*args, **kwargs)
        except Exception as exc:
            self.calls.append({"skill": name, "seconds": perf_counter() - start,
                               "status": "failed", "error_type": type(exc).__name__})
            raise
        self.calls.append({"skill": name, "seconds": perf_counter() - start, "status": "completed"})
        return output


def execute_experiment(request):
    proposal = ExperimentProposal.from_dict(request["proposal"])
    context = request["context"]
    directory = resolve_path(context["experiment_directory"])
    started = perf_counter()
    config = load_config(context["config_path"])
    registry = SkillRegistry()
    method = {"rule": "RuleSchedulingSkill", "cpsat": "CPSATOptimizationSkill", "rl": "RLPolicySkill"}
    numerical = registry.invoke(method[proposal.proposed_method], config, proposal.parameters, context)
    verification, metrics = registry.invoke("VerificationSkill", config, numerical, context)
    artifact = save_run(numerical.simulator, numerical.outcome, run_id="simulation",
                        output_root=directory, compress_events=True)
    atomic_record(artifact / "decisions.json", {"decisions": numerical.decisions})
    atomic_record(artifact / "verification.json", verification)
    result = {"scenario_id": proposal.scenario_id, "config_sha256": config_hash(config),
              "window_seconds": context["window_seconds"], "seed": context["seed"],
              "status": numerical.outcome["status"], "metrics": metrics, "verification": verification,
              "solver": numerical.solver, "model": numerical.model, "artifact_directory": relative_path(artifact),
              "skill_calls": registry.calls, "worker_execution_seconds": perf_counter() - started}
    return result
