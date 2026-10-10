"""CFAR tests use actual equipment runs plus explicitly synthetic planner unit inputs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.config import load_config
from wafer_sched.agent.feedback import FeedbackEvaluator
from wafer_sched.agent.planner import CPBudgetPlanner, DeterministicPlanner, SemanticaLLMPlanner
from wafer_sched.agent.research_memory import ResearchMemory
from wafer_sched.agent.schemas import ExperimentProposal, config_hash
from wafer_sched.agent.skills import NumericalOutcome, SkillRegistry, replay_decisions
from wafer_sched.agent.experiment_runner import ExperimentRunner, ResearchLimits, candidate_catalogue
from wafer_sched.cpsat_solver import SolverOptions, solve_schedule
from wafer_sched.cpsat_validator import validate_solution
from wafer_sched.metrics import calculate_metrics
from wafer_sched.policies.rules import make_policy
from wafer_sched.policy_runner import run_policy
from wafer_sched.simulator import Simulator


@pytest.fixture
def actual_result():
    config = load_config(PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json")
    sim = Simulator(config)
    run = run_policy(sim, make_policy("fifo"))
    sim.run_until(100)
    verification, metrics = SkillRegistry().invoke("VerificationSkill", config,
        NumericalOutcome(sim, run.outcome, run.decisions), {"window_seconds": 100, "seed": 0})
    return {"config_sha256": config_hash(config), "window_seconds": 100, "metrics": metrics,
            "verification": verification, "wall_seconds": .1, "seed": 0, "solver": None,
            "artifact_directory": None}, config, run


def proposal(method="rule", parameters=None, **values):
    return ExperimentProposal.from_dict({"experiment_id": "round-001", "scenario_id": "A",
        "proposed_method": method, "parameters": parameters or {"policy": "fifo"},
        "expected_reason": "Unit input", "selection_reason": "Unit input",
        "estimated_budget": 3, "evidence_from_history": [], **values})


def row(result, method="rule", parameters=None, number=1):
    p = proposal(method, parameters, experiment_id=f"round-{number:03d}")
    return {"round": number, "proposal": p.to_dict(), "result": deepcopy(result),
            "acceptance": {"accepted": True, "improves_incumbent": True, "reason": "unit_input"},
            "analysis": {}, "actual_planner": "unit", "fallback_reason": None,
            "best_so_far_seconds": result["metrics"].get("makespan_seconds"), "elapsed_seconds": number,
            "next_plan": None}


@pytest.mark.parametrize("change", [
    {"proposed_method": "shell"}, {"parameters": {"policy": "fifo", "code": "x"}},
    {"scenario_id": "../escape"}, {"extra": 42}, {"estimated_budget": float("nan")},
    {"evidence_from_history": [42]}, {"parameters": {"policy": "invented"}}])
def test_schema_rejects_unsafe_or_invented_proposals(change):
    with pytest.raises((ValueError, TypeError)):
        proposal(**change)


def test_context_rejects_unknown_evidence_budget_and_models():
    candidates = {"rules": ["fifo"], "cp_budgets": [1], "models": {}}
    with pytest.raises(ValueError, match="evidence"):
        proposal(evidence_from_history=["fiction"]).validate_context("A", [], candidates, 20, 20)
    with pytest.raises(ValueError, match="budget"):
        proposal().validate_context("A", [], candidates, 2, 20)
    with pytest.raises(ValueError, match="catalogue"):
        proposal("rl", {"model_id": "unknown"}).validate_context("A", [], candidates, 20, 20)


def test_physical_verification_and_exact_metrics(actual_result):
    result, config, run = actual_result
    assert result["verification"]["valid"]
    assert result["metrics"]["makespan_seconds"] == 47
    assert result["metrics"]["finite_batch_wph"] == 108
    replica = replay_decisions(config, run.decisions, 100)
    assert calculate_metrics(replica.trace) == result["metrics"]
    assert len(replica.state.wafers[config.wafers[0].wafer_id].processing_records) == 2


def test_replay_rejects_illegal_saved_action(actual_result):
    _, config, run = actual_result
    decisions = deepcopy(run.decisions)
    decisions[0]["action"]["destination"] = "OUT"
    with pytest.raises(ValueError, match="checker"):
        replay_decisions(config, decisions, 100)


def test_feedback_rejects_incomplete_invalid_or_incomparable(actual_result):
    result, _, _ = actual_result
    evaluator = FeedbackEvaluator()
    assert evaluator.evaluate(result)["accepted"]
    wrong = deepcopy(result)
    wrong["verification"]["complete"] = False
    assert evaluator.evaluate(wrong, result)["reason"] == "incomplete_batch"
    wrong = deepcopy(result)
    wrong["verification"]["valid"] = False
    assert not evaluator.evaluate(wrong)["accepted"]
    wrong = deepcopy(result)
    wrong["config_sha256"] = "different"
    assert evaluator.evaluate(wrong, result)["reason"] == "incomparable_config_or_window"
    wrong = deepcopy(result)
    wrong["window_seconds"] = 80
    assert not evaluator.evaluate(wrong, result)["accepted"]


def test_feedback_equal_performance_uses_cost(actual_result):
    result, _, _ = actual_result
    cheaper = deepcopy(result)
    cheaper["wall_seconds"] = .05
    acceptance = FeedbackEvaluator().evaluate(cheaper, result)
    assert acceptance["accepted"] and acceptance["lower_cost"] and not acceptance["improves_incumbent"]
    assert not FeedbackEvaluator().evaluate(result, result)["accepted"]


def planner_context(history, block=0):
    return {"scenario_id": "A", "history": history,
            "analysis": {"blocking_to_processing_ratio": block, "completion_window_robot_utilization": .5,
                         "current_best_seconds": 47},
            "candidates": {"rules": ["fifo", "spt", "ect", "adaptive", "bottleneck"],
                           "cp_budgets": [1, 3, 10, 30], "models": {"medium-seed-0": {}}},
            "remaining": 80, "max_experiment_seconds": 40}


def test_same_round_different_feedback_changes_plan(actual_result):
    result, _, _ = actual_result
    history = [row(result)]
    quiet = DeterministicPlanner().propose(**planner_context(history, block=.05))
    blocked = DeterministicPlanner().propose(**planner_context(history, block=.6))
    assert quiet.proposal.parameters == {"policy": "spt"}
    assert blocked.proposal.parameters == {"policy": "bottleneck"}
    assert blocked.proposal.evidence_from_history == ["round-001"]


def test_cp_feedback_optimum_stops_unknown_escalates(actual_result):
    result, _, _ = actual_result
    cp = row(result, "cpsat", {"max_seconds": 1})
    cp["result"]["solver"] = {"status": "OPTIMAL", "restricted_model": False}
    assert DeterministicPlanner().propose(**planner_context([cp])).proposal is None
    cp["result"]["solver"] = {"status": "UNKNOWN", "relative_gap": None, "best_bound_seconds": 20}
    cp["result"]["verification"]["valid"] = False
    cp["acceptance"]["accepted"] = False
    baseline = row(result)
    cp["proposal"]["experiment_id"] = "round-002"
    decision = CPBudgetPlanner().propose(**planner_context([baseline, cp]))
    assert decision.proposal.parameters["max_seconds"] == 3


def test_cp_stagnation_stops_and_budget_cannot_infinite_loop(actual_result):
    result, _, _ = actual_result
    one = row(result, "cpsat", {"max_seconds": 1}, 2)
    two = row(result, "cpsat", {"max_seconds": 3}, 3)
    for cp in (one, two):
        cp["result"]["solver"] = {"status": "FEASIBLE", "best_bound_seconds": 20, "relative_gap": .5}
        cp["acceptance"]["improves_incumbent"] = False
    assert CPBudgetPlanner().propose(**planner_context([row(result), one, two])).proposal is None
    context = planner_context([])
    context["remaining"] = .1
    assert DeterministicPlanner().propose(**context).proposal is None


def test_llm_disabled_and_failure_are_labeled_fallback(monkeypatch):
    disabled = SemanticaLLMPlanner().propose(**planner_context([]))
    assert disabled.actual_planner == "DeterministicPlanner"
    assert disabled.fallback_reason == "research_egress_not_enabled"
    for key, value in {"ASSISTANT_LLM_BASE_URL": "https://example.com/v1", "ASSISTANT_LLM_API_KEY": "unit-secret",
                       "ASSISTANT_LLM_MODEL": "unit-model"}.items():
        monkeypatch.setenv(key, value)
    def failed(*args):
        raise RuntimeError("unit-secret must never be logged")
    fallback = SemanticaLLMPlanner(allow_llm_egress=True, transport=failed).propose(**planner_context([]))
    assert fallback.fallback_reason == "llm_failure_RuntimeError"
    assert "unit-secret" not in fallback.reason


def test_llm_valid_and_unsafe_json_proposals(monkeypatch):
    for key, value in {"ASSISTANT_LLM_BASE_URL": "https://example.com/v1", "ASSISTANT_LLM_API_KEY": "unit",
                       "ASSISTANT_LLM_MODEL": "unit"}.items():
        monkeypatch.setenv(key, value)
    def transport(*args):
        return {"choices": [{"message": {"content": json.dumps(proposal().to_dict())}}]}
    decision = SemanticaLLMPlanner(allow_llm_egress=True, transport=transport).propose(**planner_context([]))
    assert decision.actual_planner == "SemanticaLLMPlanner" and decision.fallback_reason is None
    def unsafe(*args):
        return {"choices": [{"message": {"content": '{"code":"execute me"}'}}]}
    assert SemanticaLLMPlanner(allow_llm_egress=True, transport=unsafe).propose(**planner_context([])).actual_planner == "DeterministicPlanner"


def test_real_semantica_memory_graph_and_recovery(tmp_path, actual_result):
    result, _, _ = actual_result
    manifest = {"scenario_id": "A", "config_sha256": result["config_sha256"]}
    root = tmp_path / "study"
    memory = ResearchMemory(root, manifest=manifest)
    (root / "round-001").mkdir()
    memory.commit(row(result))
    recall = memory.recall()
    assert recall["memory_ids"] == ["round-001"] and recall["graph_neighbor_count"] == 1
    assert memory.calls["store"] == 1 and memory.calls["retrieve"] == 1
    assert memory.graph.to_dict()["statistics"] == {"node_count": 3, "edge_count": 2}
    restored = ResearchMemory(root, manifest=manifest, resume=True)
    assert restored.recall()["memory_ids"] == recall["memory_ids"]
    assert restored.history == memory.history
    assert (root / "decisions.csv").read_text(encoding="utf-8").count("round-001") == 1
    with pytest.raises(ValueError, match="manifest"):
        ResearchMemory(root, manifest={**manifest, "scenario_id": "other"}, resume=True)


def test_preserved_upstream_sources_are_exact():
    root = PROJECT_ROOT / "src/wafer_sched/agent/_semantica"
    provenance = json.loads((root / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert len(provenance["files"]) == 12
    for name, expected in provenance["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


def test_unknown_cp_does_not_fabricate_feasible_plan():
    config = load_config(PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json")
    solved = solve_schedule(config, SolverOptions(max_seconds=0))
    assert solved.metadata["status"] == "UNKNOWN" and solved.schedule is None
    replay, verification = validate_solution(config, solved)
    assert replay is None and not verification["valid"]


def test_compatible_rl_executes_original_policy_and_keeps_model(actual_result):
    _, config, _ = actual_result
    specification = {"path": str(PROJECT_ROOT / "results/wafer_sched/stage5/training/medium/seed-0/models/best.zip"),
                     "training_seed": 0}
    before = hashlib.sha256(Path(specification["path"]).read_bytes()).hexdigest()
    registry = SkillRegistry()
    numerical = registry.invoke("RLPolicySkill", config, {"model_id": "model"},
        {"models": {"model": specification}, "seed": 0, "window_seconds": 100, "max_decisions": 512})
    verification, metrics = registry.invoke("VerificationSkill", config, numerical, {"window_seconds": 100, "seed": 0})
    assert verification["valid"] and metrics["makespan_seconds"] == 47
    assert before == hashlib.sha256(Path(specification["path"]).read_bytes()).hexdigest()
    assert all(decision["action"] in decision["legal_actions"] for decision in numerical.decisions)


def test_model_scope_rejects_too_many_wafers():
    config = load_config(PROJECT_ROOT / "configs/wafer_sched/B_batch.json")
    models = {"model": {"path": "results/wafer_sched/stage5/training/medium/seed-0/models/best.zip", "training_seed": 0}}
    effective, rejected = candidate_catalogue(config, ["fifo"], [1], models)
    assert not effective["models"] and rejected["model"]["status"] == "not_compatible_not_executed"


def test_runner_boundary_resume_limits_and_no_overwrite(tmp_path):
    from wafer_sched.agent.planner import FixedOrderPlanner
    config = PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json"
    order = [("rule", {"policy": "fifo"}), ("rule", {"policy": "spt"})]
    kwargs = {"config_path": config, "scenario_id": "A", "window_seconds": 100,
              "planner": FixedOrderPlanner(order), "output_root": tmp_path / "run",
              "candidates": {"rules": ["fifo", "spt"], "cp_budgets": [1], "models": {}},
              "limits": ResearchLimits(max_rounds=2, total_seconds=30, max_experiment_seconds=10)}
    first = ExperimentRunner().run(**kwargs, pause_after=1)
    assert first["rounds"] == 1 and first["stop_reason"] == "paused_at_experiment_boundary"
    final = ExperimentRunner().run(**kwargs, resume=True)
    assert final["rounds"] == 2 and final["best_makespan_seconds"] == 47
    records = [json.loads(line) for line in (kwargs["output_root"] / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(r["result"]["verification"]["valid"] for r in records)
    assert ExperimentRunner().run(**kwargs, resume=True)["rounds"] == 2
    with pytest.raises(FileExistsError):
        ExperimentRunner().run(**kwargs)


def test_worker_timeout_has_no_fabricated_metrics_or_accepted_candidate(tmp_path, monkeypatch):
    import subprocess
    from wafer_sched.agent.planner import FixedOrderPlanner
    from wafer_sched.agent import experiment_runner
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("fixed_worker_module", .01)
    monkeypatch.setattr(experiment_runner.subprocess, "run", timeout)
    root = tmp_path / "timeout"
    summary = ExperimentRunner().run(config_path=PROJECT_ROOT / "configs/wafer_sched/minimal_demo.json",
        scenario_id="A", window_seconds=100, planner=FixedOrderPlanner([("rule", {"policy": "fifo"})]),
        output_root=root, candidates={"rules": ["fifo"], "cp_budgets": [1], "models": {}},
        limits=ResearchLimits(max_rounds=1, total_seconds=10, max_experiment_seconds=5))
    record = json.loads((root / "round-001/record.json").read_text(encoding="utf-8"))
    assert record["result"]["metrics"] == {} and not record["acceptance"]["accepted"]
    assert record["result"]["status"] == "single_experiment_wall_timeout"
    assert summary["best_makespan_seconds"] is None


def test_duplicate_proposals_and_mutated_parameters_are_rejected(actual_result):
    result, _, _ = actual_result
    with pytest.raises(ValueError, match="Duplicate"):
        proposal(experiment_id="round-002").validate_context("A", [row(result)],
            {"rules": ["fifo"], "cp_budgets": [1], "models": {}}, 20, 20)
    candidate = proposal()
    candidate.parameters["policy"] = "unregistered"
    with pytest.raises(ValueError):
        candidate.validate_context("A", [], {"rules": ["fifo"], "cp_budgets": [1], "models": {}}, 20, 20)


def test_holdout_requires_prior_freeze(tmp_path):
    from wafer_sched.agent.evaluation import StageSixEvaluation
    evaluation = StageSixEvaluation(PROJECT_ROOT / "configs/wafer_sched/agent/stage6_study.json", tmp_path / "holdout")
    with pytest.raises(ValueError, match="Freeze"):
        evaluation.holdout()


def test_sealed_scenarios_differ_physically_from_old_train_and_test_configs():
    fresh_paths = list((PROJECT_ROOT / "configs/wafer_sched/agent").glob("U_*.json"))
    assert len(fresh_paths) == 2
    previous = list((PROJECT_ROOT / "configs/wafer_sched").glob("*.json"))
    previous += list((PROJECT_ROOT / "configs/wafer_sched/rl").glob("[TV]_*.json"))
    for fresh_path in fresh_paths:
        fresh = load_config(fresh_path).to_dict()
        fresh.pop("name")
        for path in previous:
            if "suite" in path.name or "retry" in path.name:
                continue
            old = load_config(path).to_dict()
            old.pop("name")
            assert fresh != old


def test_problem_analysis_exposes_methods_and_history_based_budget_advice(actual_result):
    result, config, _ = actual_result
    candidates = {"rules": ["fifo"], "cp_budgets": [1, 3, 10], "models": {}}
    registry = SkillRegistry()
    initial = registry.invoke("ProblemAnalysisSkill", config, [], candidates)
    assert initial["available_methods"] == {"rule": ["fifo"], "cpsat": [1, 3, 10], "rl": []}
    assert initial["budget_advice"]["next_untried_cp_search_seconds"] == 1
    cp = row(result, "cpsat", {"max_seconds": 1})
    cp["result"]["solver"] = {"status": "FEASIBLE", "restricted_model": False}
    next_analysis = registry.invoke("ProblemAnalysisSkill", config, [cp], candidates)
    assert next_analysis["budget_advice"]["next_untried_cp_search_seconds"] == 3
    cp["result"]["solver"]["status"] = "OPTIMAL"
    stop = registry.invoke("ProblemAnalysisSkill", config, [cp], candidates)
    assert stop["budget_advice"]["next_untried_cp_search_seconds"] is None
