"""Real graph/numerical tests; fake LLM responses are explicitly nonexperimental."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile

import pytest

pytest.importorskip(
    "langgraph", reason="Optional stage-seven orchestration is not installed"
)

from wafer_sched.infrastructure.paths import PROJECT_ROOT
from wafer_sched.langgraph_agent.code_improvement import CodeImprovementSkill
from wafer_sched.langgraph_agent.graph import ResearchRuntime
from wafer_sched.langgraph_agent.llm import (
    LLMClient,
    LLMSettings,
    LLMUnavailable,
    local_configuration,
)
from wafer_sched.langgraph_agent.schemas import (
    Limits,
    PlannerProposal,
    validate_proposal,
)
from wafer_sched.langgraph_agent.tools import TOOL_SCHEMAS


@pytest.fixture
def temporary_root():
    parent = PROJECT_ROOT / "results/local/stage7-unit-tests"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        yield Path(directory)


@pytest.fixture
def study():
    value = json.loads(
        (PROJECT_ROOT / "configs/wafer_sched/langgraph/stage7_study.json").read_text(
            encoding="utf-8"
        )
    )
    value["limits"].update(max_rounds=5, total_seconds=60.0, max_llm_calls=14)
    value["candidates"]["models"] = {}
    value["candidates"]["cp_budgets"] = [1]
    return value


def proposal(round_number=1, method="rule", parameters=None):
    sid = "F_competition" if round_number % 2 else "G_dual_bottleneck"
    policy = ["fifo", "spt", "ect", "bottleneck", "adaptive"][(round_number - 1) // 2]
    return {
        "action": "experiment",
        "scenario_id": sid,
        "method": method,
        "parameters": parameters or {"policy": policy},
        "rationale": "Explicit unit-test input",
        "hypothesis": "Test an allowed candidate",
        "expected_effect": "Measure and independently replay",
        "evidence": [],
    }


def mock_transport(_settings, body, _deadline):
    context = json.loads(body["messages"][1]["content"])
    if "latest_result" in context:
        data = {
            "explanation": "Unit response: read supplied verification, never create metrics",
            "failure_explanation": "",
            "testable_hypothesis": "Evaluate a distinct rule next",
            "next_proposal": proposal(context["next_global_round"] + 1),
        }
    else:
        data = proposal(context["next_global_round"])
    return {
        "http_status": 200,
        "response": {
            "model": "unit-model",
            "id": "unit-response",
            "choices": [{"message": {"content": json.dumps(data)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        },
    }


def unit_client(root, limits, transport=mock_transport):
    settings = LLMSettings("https://unit.invalid", "unit-model", "unit-secret")
    return LLMClient(
        settings, limits, root / "mock_llm_calls.jsonl", transport=transport
    )


def validation_context():
    candidates = {
        n: {"rules": ["fifo"], "cp_budgets": [1], "models": {}}
        for n in ["F_competition", "G_dual_bottleneck"]
    }
    return {
        "scenarios": dict.fromkeys(candidates),
        "histories": {n: [] for n in candidates},
        "candidates": candidates,
        "remaining": 60,
        "max_experiment_seconds": 40,
        "next_round": 1,
        "cp_remaining": 60,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"method": "shell"},
        {"parameters": {"policy": "fifo", "python": "print(1)"}},
        {"scenario_id": "../escape"},
        {"evidence": ["invented"]},
        {"parameters": {"policy": "not_registered"}},
        {"estimated_budget": 0.01},
        {"method": "rl", "parameters": {"model_id": "../weights"}},
        {"method": "cpsat", "parameters": {"max_seconds": 30}},
    ],
)
def test_llm_proposal_cannot_escape_schema_catalogue_or_evidence(change):
    with pytest.raises((ValueError, KeyError, TypeError)):
        validate_proposal({**proposal(), **change}, **validation_context())


def test_admission_is_computed_by_server_not_llm():
    _, p = validate_proposal(proposal(), **validation_context())
    assert p.estimated_budget == 3 and p.experiment_id == "round-001"
    with pytest.raises(ValueError):
        validate_proposal(proposal(), **{**validation_context(), "remaining": 2})
    with pytest.raises(ValueError):
        validate_proposal(
            proposal(method="cpsat", parameters={"max_seconds": 1}),
            **{**validation_context(), "cp_remaining": 0.5},
        )


def test_stop_does_not_claim_a_measured_result():
    raw = {
        **proposal(),
        "action": "stop",
        "scenario_id": None,
        "method": None,
        "parameters": {},
    }
    _, p = validate_proposal(raw, **validation_context())
    assert p is None
    with pytest.raises(ValueError):
        PlannerProposal.model_validate({**raw, "makespan": 63})


def test_dotenv_loader_precedence_and_no_execution(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        'ASSISTANT_LLM_BASE_URL=https://unit.invalid\nASSISTANT_LLM_MODEL="from-file"\n'
        "ASSISTANT_LLM_API_KEY=unit-secret\nUNRELATED=$(must_not_execute)\n",
        encoding="utf-8",
    )
    values = local_configuration(env, {"ASSISTANT_LLM_MODEL": "from-process"})
    assert values["ASSISTANT_LLM_MODEL"] == "from-file" and len(values) == 3
    assert (
        local_configuration(env, {"ASSISTANT_LLM_API_KEY": "old-process-secret"})[
            "ASSISTANT_LLM_API_KEY"
        ]
        == "unit-secret"
    )
    assert "unit-secret" not in repr(
        LLMSettings("https://unit.invalid", "m", "unit-secret")
    )


def test_explicit_empty_dotenv_does_not_reuse_old_process_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ASSISTANT_LLM_API_KEY=\n", encoding="utf-8")
    assert (
        local_configuration(env, {"ASSISTANT_LLM_API_KEY": "stale-secret"})[
            "ASSISTANT_LLM_API_KEY"
        ]
        == ""
    )


def test_default_loader_never_reads_process_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "stale-process-secret")
    monkeypatch.setenv("ASSISTANT_LLM_MODEL", "stale-process-model")
    assert local_configuration(tmp_path / "missing.env")["ASSISTANT_LLM_API_KEY"] == ""
    env = tmp_path / ".env"
    env.write_text(
        "ASSISTANT_LLM_BASE_URL=https://unit.invalid\nASSISTANT_LLM_MODEL=new-model\nASSISTANT_LLM_API_KEY=new-file-secret\n",
        encoding="utf-8",
    )
    settings = LLMSettings.from_local(env)
    assert settings.api_key == "new-file-secret" and settings.model == "new-model"


def test_provider_error_redacts_credentials_and_omits_headers():
    from wafer_sched.langgraph_agent.http_worker import safe_provider_error

    body = {
        "error": {
            "type": "authentication_error",
            "code": "invalid_api_key",
            "message": "Authentication fails: api key: unit-secret is invalid; Bearer other-credential; sk-another-credential",
            "authorization": "must-not-be-exported",
        },
        "headers": {"cookie": "private"},
    }
    result = safe_provider_error(json.dumps(body).encode(), "unit-secret")
    assert set(result) == {"type", "code", "message"}
    assert result["type"] == "authentication_error"
    assert result["code"] == "invalid_api_key"
    assert all(
        value not in json.dumps(result)
        for value in (
            "unit-secret",
            "other-credential",
            "sk-another-credential",
            "must-not-be-exported",
            "private",
        )
    )
    assert (
        safe_provider_error(b"non-json private response", "unit-secret")["message"]
        == "Non-JSON or nonstandard error body omitted"
    )


def test_http_error_is_logged_without_credentials_or_fake_tokens(tmp_path):
    def reject(*_args):
        return {
            "http_status": 401,
            "error": "http_401",
            "provider_error": {
                "type": "authentication_error",
                "message": "unit-secret invalid",
            },
        }

    client = unit_client(tmp_path, Limits(), reject)
    with pytest.raises(LLMUnavailable, match="http_401"):
        client.call("unit", {}, PlannerProposal, 20)
    text = (tmp_path / "mock_llm_calls.jsonl").read_text(encoding="utf-8")
    assert "unit-secret" not in text
    record = json.loads(text)
    assert record["usage"] is None and record["status"] == "failed"
    assert record["provider_error"]["type"] == "authentication_error"
    assert "[REDACTED]" in record["provider_error"]["message"]
    assert client.totals()["successful_api_calls"] == 0


def test_no_network_request_if_token_or_fee_reservation_exceeds_budget(tmp_path):
    count = []

    def transport(*_args):
        count.append(1)
        raise AssertionError("Must not call")

    client = unit_client(tmp_path, Limits(max_total_tokens=100), transport)
    with pytest.raises(LLMUnavailable, match="budget"):
        client.call("unit", {}, PlannerProposal, 20)
    assert not count


def test_real_graph_five_mock_planned_rounds_use_actual_simulator_but_never_count_as_live(
    study, temporary_root
):
    client = unit_client(temporary_root, Limits.model_validate(study["limits"]))
    runtime = ResearchRuntime(study, "llm", temporary_root / "session", client=client)
    try:
        summary = runtime.run()
        assert len(runtime.tools.structured_tools()) == 7
        assert set(TOOL_SCHEMAS) == {t.name for t in runtime.tools.structured_tools()}
        assert summary["rounds"] == 5 and summary["all_recorded_candidates_verified"]
        assert (
            summary["real_llm_planned_rounds"] == 0
            and not summary["real_llm_acceptance_passed"]
        )
        assert all(
            r["result"]["verification"]["graph_replay_verified"]
            for r in runtime.memory.records
        )
        assert runtime.memory.records[0]["result"]["metrics"]["makespan_seconds"] == 74
        trace = [
            json.loads(line)
            for line in (runtime.root / "graph_trace.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        nodes = {r["node"] for r in trace}
        assert nodes == {
            "ProblemUnderstanding",
            "ResearchPlanner",
            "ProposalValidator",
            "SkillExecutor",
            "MathematicalVerifier",
            "ResultAnalyzer",
            "ResearchReflection",
            "ResearchMemory",
            "TerminationController",
        }
        assert sum(r["node"] == "ResearchPlanner" for r in trace) == 5
        assert runtime.memory.records[0]["next_plan"] is not None
        assert len(runtime.memory.histories["F_competition"].history) == 3
    finally:
        runtime.close()


def test_persistent_resume_at_boundary_does_not_repeat_previous_tool(
    study, temporary_root
):
    study["limits"]["max_rounds"] = 2
    root = temporary_root / "resume"
    runtime = ResearchRuntime(study, "deterministic", root)
    try:
        paused = runtime.run(pause_after=1)
        assert paused["status"] == "paused" and paused["rounds"] == 1
        original_result = deepcopy(runtime.memory.records[0]["result"])
        assert runtime.graph.get_state(runtime.graph_config).next == (
            "TerminationController",
        )
    finally:
        runtime.close()
    runtime = ResearchRuntime(study, "deterministic", root, resume=True)
    try:
        finished = runtime.run(resume=True)
        assert finished["rounds"] == 2
        assert runtime.memory.records[0]["result"] == original_result
        numerical = [
            json.loads(s)
            for s in (root / "tool_calls.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if json.loads(s)["tool"]
            in {"rule_scheduling", "cpsat_optimization", "rl_policy_evaluation"}
        ]
        assert len(numerical) == 2
    finally:
        runtime.close()


def test_invalid_llm_proposal_falls_back_with_true_planner_label(study, temporary_root):
    study["limits"]["max_rounds"] = 1

    def invalid(_settings, body, _deadline):
        data = proposal()
        data["parameters"] = {"policy": "invented"}
        return {
            "http_status": 200,
            "response": {
                "choices": [{"message": {"content": json.dumps(data)}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        }

    runtime = ResearchRuntime(
        study,
        "llm",
        temporary_root / "fallback",
        client=unit_client(temporary_root, Limits(), invalid),
    )
    try:
        summary = runtime.run()
        assert (
            summary["fallback_rounds"] == 1 and summary["real_llm_planned_rounds"] == 0
        )
        row = runtime.memory.records[0]
        assert (
            row["actual_planner"] == "DeterministicPlanner" and row["fallback_reason"]
        )
        assert row["result"]["verification"]["valid"]
        assert (runtime.root / "proposal_rejections.jsonl").exists()
        assert row["raw_llm_proposal"]["parameters"]["policy"] == "invented"
        assert row["proposal"]["parameters"]["policy"] == "fifo"
        assert row["planner_call"]["evidence_source"] == "unit_test_mock"
    finally:
        runtime.close()


def test_output_guard_no_overwrite_and_resume_identity(study, temporary_root):
    with pytest.raises(ValueError, match="Output"):
        ResearchRuntime(
            study, "fixed", PROJECT_ROOT / "results/wafer_sched/stage6/forbidden"
        )
    root = temporary_root / "identity"
    runtime = ResearchRuntime(study, "fixed", root)
    runtime.close()
    with pytest.raises(FileExistsError):
        ResearchRuntime(study, "fixed", root)
    different = deepcopy(study)
    different["limits"]["total_seconds"] = 61.0
    with pytest.raises(ValueError, match="identity"):
        ResearchRuntime(different, "fixed", root, resume=True)


def test_code_improvement_cannot_execute():
    assert not CodeImprovementSkill.enabled
    with pytest.raises(RuntimeError, match="disabled"):
        CodeImprovementSkill().execute("print('must not execute')")


@pytest.mark.parametrize(
    "method,parameters",
    [("cpsat", {"max_seconds": 3}), ("rl", {"model_id": "medium-seed-0"})],
)
def test_real_cp_and_preserved_ppo_are_executable_typed_tools(
    study, temporary_root, method, parameters
):
    original = json.loads(
        (PROJECT_ROOT / "configs/wafer_sched/langgraph/stage7_study.json").read_text(
            encoding="utf-8"
        )
    )
    study["candidates"]["models"] = original["candidates"]["models"]
    study["candidates"]["cp_budgets"] = [1, 3]
    runtime = ResearchRuntime(study, "deterministic", temporary_root / method)
    try:
        _, p = runtime._validate(
            proposal(method=method, parameters=parameters), {"round": 0}
        )
        runtime.tools.current = p.to_dict()
        name = {"cpsat": "cpsat_optimization", "rl": "rl_policy_evaluation"}[method]
        tool = next(t for t in runtime.tools.structured_tools() if t.name == name)
        numerical = tool.invoke({"scenario_id": "F_competition", **parameters})
        assert numerical["ok"]
        verified = runtime.tools.invoke(
            "constraint_verification",
            {"scenario_id": "F_competition", "experiment_id": "round-001"},
        )
        assert verified["ok"] and verified["output"]["valid"]
        if method == "rl":
            assert numerical["output"]["model"]["retrained"] is False
            assert numerical["output"]["metrics"]["makespan_seconds"] == 65
        else:
            assert numerical["output"]["solver"]["status"] in {"FEASIBLE", "OPTIMAL"}
    finally:
        runtime.close()


def test_unknown_and_timeout_do_not_fabricate_a_plan(study, temporary_root):
    study["candidates"]["cp_budgets"] = [0.000001]
    runtime = ResearchRuntime(study, "deterministic", temporary_root / "unknown")
    try:
        _, p = runtime._validate(
            proposal(method="cpsat", parameters={"max_seconds": 0.000001}), {"round": 0}
        )
        runtime.tools.current = p.to_dict()
        result = runtime.tools.invoke(
            "cpsat_optimization",
            {"scenario_id": "F_competition", "max_seconds": 0.000001},
        )
        assert result["ok"] and result["output"]["solver"]["status"] == "UNKNOWN"
        assert not result["output"]["verification"]["valid"]
        assert result["output"]["metrics"]["makespan_seconds"] is None
        _, p = runtime._validate(proposal(2), {"round": 1})
        runtime.tools.current = p.to_dict()
        runtime.tools.deadline = 0.001
        failed = runtime.tools.invoke(
            "rule_scheduling", {"scenario_id": "G_dual_bottleneck", "policy": "fifo"}
        )
        assert (
            failed["ok"]
            and failed["output"]["status"] == "single_experiment_wall_timeout"
        )
        assert (
            failed["output"]["metrics"] == {}
            and not failed["output"]["verification"]["valid"]
        )
    finally:
        runtime.close()
