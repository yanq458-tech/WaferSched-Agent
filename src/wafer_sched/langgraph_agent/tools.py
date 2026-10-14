"""Seven typed Agent tools, backed exclusively by the original numerical code."""

import json
import subprocess
import sys
from time import perf_counter

from pydantic import Field

from wafer_sched.agent.feedback import FeedbackEvaluator
from wafer_sched.agent.schemas import ExperimentProposal, config_hash
from wafer_sched.agent.skills import SkillRegistry, replay_decisions
from wafer_sched.config import load_config
from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.paths import PROJECT_ROOT, relative_path, resolve_path
from wafer_sched.metrics import calculate_metrics

from .llm import append_jsonl
from .schemas import ClosedModel


class ScenarioInput(ClosedModel):
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class RuleInput(ScenarioInput):
    policy: str


class CPInput(ScenarioInput):
    max_seconds: float = Field(gt=0, le=30)


class RLInput(ScenarioInput):
    model_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class ArtifactInput(ScenarioInput):
    experiment_id: str = Field(pattern=r"^round-[0-9]{3}$")


class ComparisonInput(ArtifactInput):
    incumbent_id: str | None


TOOL_SCHEMAS = {
    "rule_scheduling": RuleInput,
    "cpsat_optimization": CPInput,
    "rl_policy_evaluation": RLInput,
    "equipment_simulation": ArtifactInput,
    "constraint_verification": ArtifactInput,
    "experiment_comparison": ComparisonInput,
    "research_history_query": ScenarioInput,
}


class AgentTools:
    def __init__(self, scenarios, candidates, memories, limits, log_path, seed=0):
        self.scenarios, self.candidates, self.memories = scenarios, candidates, memories
        self.limits, self.log_path, self.seed = limits, log_path, seed
        self.registry = SkillRegistry()
        self.current = None
        self.deadline = limits.max_experiment_seconds
        self.results = {
            r["proposal"]["experiment_id"]: r["result"]
            for m in memories.values()
            for r in m.history
        }

    def structured_tools(self):
        """Real LangChain tool objects usable by future ToolNode integrations."""
        from langchain_core.tools import StructuredTool

        tools = []
        for name, schema in TOOL_SCHEMAS.items():

            def call(_name=name, **kwargs):
                return self.invoke(_name, kwargs)

            tools.append(
                StructuredTool.from_function(
                    call,
                    name=name,
                    args_schema=schema,
                    description="Typed WaferSched tool. Returns ok/output or error_type; "
                    "uses only configured development instances and approved experiment IDs.",
                )
            )
        return tools

    def invoke(self, name, request):
        started = perf_counter()
        try:
            if name not in TOOL_SCHEMAS:
                raise ValueError("Unknown tool")
            args = TOOL_SCHEMAS[name].model_validate(request).model_dump()
            if args["scenario_id"] not in self.scenarios:
                raise ValueError("Unknown development scenario")
            output = getattr(self, "_" + name)(**args)
            response = {"ok": True, "tool": name, "output": output}
        except Exception as exc:
            response = {"ok": False, "tool": name, "error_type": type(exc).__name__}
        response["wall_seconds"] = perf_counter() - started
        append_jsonl(self.log_path, {"input": request, **response})
        return response

    def _research_history_query(self, scenario_id):
        memory = self.memories[scenario_id]
        recall = memory.recall()
        return {"recall": recall, "history": json.loads(json.dumps(memory.history))}

    def _rule_scheduling(self, scenario_id, policy):
        if policy not in self.candidates[scenario_id]["rules"]:
            raise ValueError("Rule not allowlisted")
        return self._execute(scenario_id, "rule", {"policy": policy})

    def _cpsat_optimization(self, scenario_id, max_seconds):
        if max_seconds not in self.candidates[scenario_id]["cp_budgets"]:
            raise ValueError("CP budget not allowlisted")
        return self._execute(scenario_id, "cpsat", {"max_seconds": max_seconds})

    def _rl_policy_evaluation(self, scenario_id, model_id):
        if model_id not in self.candidates[scenario_id]["models"]:
            raise ValueError("Pretrained model not allowlisted")
        return self._execute(scenario_id, "rl", {"model_id": model_id})

    def _execute(self, scenario_id, method, parameters):
        proposal = ExperimentProposal.from_dict(self.current)
        if (proposal.scenario_id, proposal.proposed_method, proposal.parameters) != (
            scenario_id,
            method,
            parameters,
        ):
            raise ValueError("Invocation differs from validated proposal")
        memory = self.memories[scenario_id]
        directory = memory.root / proposal.experiment_id
        directory.mkdir(exist_ok=False)
        accepted = [r["result"] for r in memory.history if r["acceptance"]["accepted"]]
        context = {
            "config_path": self.scenarios[scenario_id]["config"],
            "seed": self.seed,
            "window_seconds": self.scenarios[scenario_id]["window_seconds"],
            "experiment_directory": relative_path(directory),
            "models": self.candidates[scenario_id]["models"],
            "max_decisions": self.limits.max_decisions,
            "incumbent_directory": accepted[-1]["artifact_directory"]
            if accepted
            else None,
        }
        atomic_record(
            directory / "input.json",
            {"proposal": proposal.to_dict(), "context": context},
        )
        started = perf_counter()
        failure = None
        try:
            proc = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts/run_worker.py")],
                input=json.dumps(
                    {"proposal": proposal.to_dict(), "context": context}
                ).encode(),
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.deadline,
                check=False,
            )
            if proc.returncode:
                failure = "worker_failed"
        except subprocess.TimeoutExpired:
            failure = "single_experiment_wall_timeout"
        if failure:
            config = load_config(resolve_path(context["config_path"]))
            result = {
                "scenario_id": scenario_id,
                "config_sha256": config_hash(config),
                "window_seconds": context["window_seconds"],
                "seed": self.seed,
                "status": failure,
                "metrics": {},
                "solver": None,
                "model": None,
                "artifact_directory": None,
                "verification": {
                    "valid": False,
                    "complete": False,
                    "issues": [failure],
                    "independent_replay_valid": False,
                },
                "skill_calls": [],
            }
        else:
            result = json.loads(
                (directory / "worker_result.json").read_text(encoding="utf-8")
            )
        result["wall_seconds"] = perf_counter() - started
        self.results[proposal.experiment_id] = result
        return result

    def _equipment_simulation(self, scenario_id, experiment_id):
        result = self.results[experiment_id]
        if result["scenario_id"] != scenario_id or not result["artifact_directory"]:
            raise ValueError("No schedule artifact for this scenario")
        config = load_config(resolve_path(self.scenarios[scenario_id]["config"]))
        directory = resolve_path(result["artifact_directory"])
        decisions = json.loads(
            (directory / "decisions.json").read_text(encoding="utf-8")
        )["decisions"]
        if len(decisions) > self.limits.max_decisions:
            raise ValueError("Replay decision limit exceeded")
        sim = replay_decisions(config, decisions, result["window_seconds"], self.seed)
        return {
            "complete": sim.completed,
            "state_valid": bool(sim.validate_state()),
            "metrics": calculate_metrics(sim.trace),
            "deadlock_count": sum(e["event"] == "PotentialDeadlock" for e in sim.trace),
            "replay_source": "original_Simulator",
        }

    def _constraint_verification(self, scenario_id, experiment_id):
        result = self.results[experiment_id]
        if not result.get("artifact_directory"):
            return {
                "valid": False,
                "complete": False,
                "independent_replay_valid": False,
                "issues": ["no_replayable_candidate"],
            }
        replay_call = self.invoke(
            "equipment_simulation",
            {"scenario_id": scenario_id, "experiment_id": experiment_id},
        )
        if not replay_call["ok"]:
            return {
                "valid": False,
                "complete": False,
                "independent_replay_valid": False,
                "issues": ["independent_replay_failed"],
            }
        replay = replay_call["output"]
        verified = result["verification"]
        valid = bool(
            verified["valid"]
            and replay["complete"]
            and replay["state_valid"]
            and not replay["deadlock_count"]
            and replay["metrics"] == result["metrics"]
            and (result.get("solver") or {}).get("status") != "UNKNOWN"
        )
        return {
            **verified,
            "valid": valid,
            "independent_replay_valid": valid,
            "graph_replay_verified": valid,
            "replay_source": replay["replay_source"],
            "issues": verified.get("issues", [])
            if valid
            else ["independent_replay_not_verified"],
        }

    def _experiment_comparison(self, scenario_id, experiment_id, incumbent_id):
        result = self.results[experiment_id]
        incumbent = self.results[incumbent_id] if incumbent_id else None
        if result["scenario_id"] != scenario_id:
            raise ValueError("Wrong scenario")
        return {
            "acceptance": FeedbackEvaluator().evaluate(result, incumbent),
            "analysis": self.registry.invoke(
                "ExperimentAnalysisSkill", result, incumbent
            ),
        }
