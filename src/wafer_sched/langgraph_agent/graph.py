"""Nine-node, checkpointed feedback graph over unchanged numerical tools."""

from datetime import datetime, timezone
import json
import sqlite3
from time import perf_counter
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from wafer_sched.agent.experiment_runner import candidate_catalogue
from wafer_sched.agent.feedback import best_row
from wafer_sched.agent.planner import DeterministicPlanner, FixedOrderPlanner
from wafer_sched.agent.schemas import ExperimentProposal
from wafer_sched.agent.skills import SkillRegistry
from wafer_sched.config import load_config
from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.paths import resolve_path

from .llm import LLMClient, LLMSettings, append_jsonl
from .memory import SessionMemory
from .schemas import Limits, PlannerProposal, ResearchReflection, validate_proposal
from .tools import AgentTools


class ResearchState(TypedDict, total=False):
    round: int
    cursor: int
    elapsed_seconds: float
    cp_allocated_seconds: float
    history: list[dict]
    analyses: dict
    raw_proposal: dict | None
    original_llm_proposal: dict | None
    proposal: dict | None
    actual_planner: str
    fallback_reason: str | None
    planner_call: dict | None
    pending: dict | None
    reflection: dict | None
    last_hypothesis: dict | None
    stop_reason: str | None
    terminal: bool


class ResearchRuntime:
    def __init__(self, study, mode, output, *, seed=0, resume=False, client=None):
        self.started = perf_counter()
        self.prior_elapsed = 0.0
        self.study = study
        self.limits = Limits.model_validate(study["limits"])
        if mode not in {"deterministic", "llm", "fixed"}:
            raise ValueError("Unknown study arm")
        self.mode, self.seed = mode, seed
        self.scenarios = {s["name"]: s for s in study["development"]}
        if not self.scenarios or len(self.scenarios) != len(study["development"]):
            raise ValueError("Scenario list is empty or duplicated")
        self.configs, self.candidates = {}, {}
        for name, spec in self.scenarios.items():
            self.configs[name] = load_config(resolve_path(spec["config"]))
            self.candidates[name], _ = candidate_catalogue(
                self.configs[name], **study["candidates"]
            )
        settings = LLMSettings.from_local(resolve_path(".env"), study.get("llm", {}))
        self.memory = SessionMemory(
            output, study, self.candidates, mode, settings.public(), seed, resume
        )
        self.root = self.memory.root
        self.client = client or LLMClient(
            settings, self.limits, self.root / "llm_calls.jsonl"
        )
        self.registry = SkillRegistry()
        self.tools = AgentTools(
            self.scenarios,
            self.candidates,
            self.memory.histories,
            self.limits,
            self.root / "tool_calls.jsonl",
            seed,
        )
        self.names = list(self.scenarios)
        self.planners = {
            n: FixedOrderPlanner(study["fixed_order"])
            if mode == "fixed"
            else DeterministicPlanner()
            for n in self.names
        }
        self.connection = sqlite3.connect(
            self.root / "checkpoints.sqlite", check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self.connection)
        self.graph = self.build_graph()
        self.graph_config = {
            "configurable": {"thread_id": "wafer-research"},
            "recursion_limit": 25 * self.limits.max_rounds + 10,
        }
        atomic_record(
            self.root / "tool_schemas.json",
            {
                t.name: t.args_schema.model_json_schema()
                for t in self.tools.structured_tools()
            },
        )
        (self.root / "workflow.mmd").write_text(
            self.graph.get_graph().draw_mermaid(), encoding="utf-8"
        )

    def elapsed(self):
        return self.prior_elapsed + perf_counter() - self.started

    def remaining(self):
        return max(0.0, self.limits.total_seconds - self.elapsed())

    def _wrap(self, name, handler):
        def node(state):
            started = perf_counter()
            try:
                result = handler(state)
                result["elapsed_seconds"] = self.elapsed()
                append_jsonl(
                    self.root / "graph_trace.jsonl",
                    {
                        "node": name,
                        "round_before": state.get("round", 0),
                        "status": "completed",
                        "wall_seconds": perf_counter() - started,
                        "update": result,
                    },
                )
                return result
            except Exception as exc:
                append_jsonl(
                    self.root / "graph_trace.jsonl",
                    {
                        "node": name,
                        "round_before": state.get("round", 0),
                        "status": "failed",
                        "wall_seconds": perf_counter() - started,
                        "error_type": type(exc).__name__,
                    },
                )
                raise

        return node

    def build_graph(self):
        builder = StateGraph(ResearchState)
        nodes = {
            "ProblemUnderstanding": self.problem_understanding,
            "ResearchPlanner": self.research_planner,
            "ProposalValidator": self.proposal_validator,
            "SkillExecutor": self.skill_executor,
            "MathematicalVerifier": self.mathematical_verifier,
            "ResultAnalyzer": self.result_analyzer,
            "ResearchReflection": self.research_reflection,
            "ResearchMemory": self.research_memory,
            "TerminationController": self.termination_controller,
        }
        for name, handler in nodes.items():
            builder.add_node(name, self._wrap(name, handler))
        builder.add_edge(START, "ProblemUnderstanding")
        builder.add_edge("ProblemUnderstanding", "ResearchPlanner")
        builder.add_edge("ResearchPlanner", "ProposalValidator")
        builder.add_conditional_edges(
            "ProposalValidator",
            lambda s: "stop" if s.get("terminal") else "execute",
            {"stop": "TerminationController", "execute": "SkillExecutor"},
        )
        builder.add_edge("SkillExecutor", "MathematicalVerifier")
        builder.add_edge("MathematicalVerifier", "ResultAnalyzer")
        builder.add_edge("ResultAnalyzer", "ResearchReflection")
        builder.add_edge("ResearchReflection", "ResearchMemory")
        builder.add_edge("ResearchMemory", "TerminationController")
        builder.add_conditional_edges(
            "TerminationController",
            lambda s: "stop" if s["terminal"] else "continue",
            {"stop": END, "continue": "ProblemUnderstanding"},
        )
        # Persistent pause is AFTER a complete experiment commit. invoke(None)
        # resumes TerminationController and the feedback edge, not a fixed tool list.
        return builder.compile(
            checkpointer=self.checkpointer, interrupt_after=["ResearchMemory"]
        )

    def problem_understanding(self, state):
        analyses = {}
        for name in self.names:
            recalled = self.tools.invoke(
                "research_history_query", {"scenario_id": name}
            )
            if not recalled["ok"]:
                raise RuntimeError("ResearchMemory recall failed")
            analyses[name] = self.registry.invoke(
                "ProblemAnalysisSkill",
                self.configs[name],
                recalled["output"]["history"],
                self.candidates[name],
            )
        return {"analyses": analyses}

    def planner_context(self, state):
        history = [
            {
                "experiment_id": r["proposal"]["experiment_id"],
                "scenario_id": r["proposal"]["scenario_id"],
                "method": r["proposal"]["proposed_method"],
                "parameters": r["proposal"]["parameters"],
                "verified": r["result"]["verification"]["valid"],
                "makespan_seconds": r["result"]["metrics"].get("makespan_seconds"),
                "solver_status": (r["result"].get("solver") or {}).get("status"),
                "restricted_model": (r["result"].get("solver") or {}).get(
                    "restricted_model"
                ),
                "solver_bound": (r["result"].get("solver") or {}).get(
                    "best_bound_seconds"
                ),
                "tool_seconds": r["result"]["wall_seconds"],
                "acceptance": r["acceptance"],
                "analysis": r["analysis"],
            }
            for r in self.memory.records
        ]
        return {
            "objective": "minimize verified complete-batch Makespan within each scenario; "
            "then compare tool cost; do not compare raw Makespan across scenarios",
            "next_global_round": state.get("round", 0) + 1,
            "analysis": state["analyses"],
            "allowed": {
                n: {
                    "rules": c["rules"],
                    "cp_budgets": c["cp_budgets"],
                    "model_ids": list(c["models"]),
                }
                for n, c in self.candidates.items()
            },
            "remaining_wall_seconds": self.remaining(),
            "max_experiment_seconds": self.limits.max_experiment_seconds,
            "cp_search_seconds_remaining": self.limits.max_cp_seconds_total
            - state.get("cp_allocated_seconds", 0),
            "llm_cost_and_tokens": self.client.totals(),
            "history": history,
            "parameter_contract": {
                "rule": {"policy": "choose exactly one allowed.rules value"},
                "cpsat": {
                    "max_seconds": "choose exactly one allowed.cp_budgets numeric value, within remaining CP budget"
                },
                "rl": {"model_id": "choose exactly one allowed.model_ids value"},
                "extra_parameter_keys": "forbidden",
            },
            "evidence_contract": {
                "permitted_experiment_ids": [r["experiment_id"] for r in history],
                "format": "IDs only, never descriptive text; [] is valid and required with empty history",
            },
            "mathematical_interpretation": "Nominal chamber loads are lower bounds, not measured batch completion times. Hypotheses are unverified. Only Simulator establishes feasibility and solver OPTIMAL establishes optimality within its declared model.",
            "previous_reflection": state.get("last_hypothesis"),
            "tool_mapping": {
                "rule": "rule_scheduling",
                "cpsat": "cpsat_optimization",
                "rl": "rl_policy_evaluation",
            },
        }

    def baseline_plan(self, state, fallback_reason=None):
        histories = self.memory.histories_as_values()
        cursor = state.get("cursor", 0)
        for offset in range(len(self.names)):
            index = (cursor + offset) % len(self.names)
            name = self.names[index]
            context = {
                "scenario_id": name,
                "history": histories[name],
                "analysis": state["analyses"][name],
                "candidates": self.candidates[name],
                "remaining": self.remaining(),
                "max_experiment_seconds": self.limits.max_experiment_seconds,
            }
            planner = self.planners[name]
            decision = planner.propose(**context)
            if decision.proposal:
                p = decision.proposal.to_dict()
                raw = {
                    "action": "experiment",
                    "scenario_id": name,
                    "method": p["proposed_method"],
                    "parameters": p["parameters"],
                    "rationale": p["selection_reason"],
                    "hypothesis": p["expected_reason"],
                    "expected_effect": "test the declared candidate",
                    "evidence": p["evidence_from_history"],
                }
                return {
                    "raw_proposal": raw,
                    "actual_planner": decision.actual_planner,
                    "fallback_reason": fallback_reason,
                    "cursor": (index + 1) % len(self.names),
                }
        return {
            "raw_proposal": {
                "action": "stop",
                "scenario_id": None,
                "method": None,
                "parameters": {},
                "rationale": "No affordable useful candidate remains",
                "hypothesis": "Candidate catalogue exhausted within the current budget",
                "expected_effect": "stop",
                "evidence": [],
            },
            "actual_planner": planner.name,
            "fallback_reason": fallback_reason,
        }

    def research_planner(self, state):
        if self.mode != "llm":
            return {
                **self.baseline_plan(state),
                "planner_call": None,
                "original_llm_proposal": None,
            }
        try:
            raw, call = self.client.call(
                "ResearchPlanner",
                self.planner_context(state),
                PlannerProposal,
                self.remaining(),
            )
            return {
                "raw_proposal": raw,
                "original_llm_proposal": raw,
                "actual_planner": "LangGraphLLMPlanner",
                "fallback_reason": None,
                "planner_call": {
                    k: call.get(k)
                    for k in [
                        "call_id",
                        "model",
                        "evidence_source",
                        "status",
                        "http_status",
                        "usage",
                    ]
                },
            }
        except Exception as exc:
            code = type(exc).__name__ + ":" + str(exc)
            if self.study.get("allow_deterministic_fallback", True):
                call = self.client.records[-1] if self.client.records else {}
                return {
                    **self.baseline_plan(state, code),
                    "original_llm_proposal": None,
                    "planner_call": {
                        k: call.get(k)
                        for k in [
                            "call_id",
                            "model",
                            "evidence_source",
                            "status",
                            "http_status",
                            "usage",
                        ]
                    },
                }
            return {
                "raw_proposal": None,
                "original_llm_proposal": None,
                "planner_call": None,
                "actual_planner": "unavailable",
                "fallback_reason": code,
                "terminal": True,
                "stop_reason": "llm_planning_failed",
            }

    def _validate(self, raw, state):
        return validate_proposal(
            raw,
            scenarios=self.scenarios,
            histories=self.memory.histories_as_values(),
            candidates=self.candidates,
            remaining=self.remaining(),
            max_experiment_seconds=self.limits.max_experiment_seconds,
            next_round=state.get("round", 0) + 1,
            cp_remaining=self.limits.max_cp_seconds_total
            - state.get("cp_allocated_seconds", 0),
        )

    def proposal_validator(self, state):
        if state.get("terminal"):
            return {"proposal": None}
        update = {}
        raw = state["raw_proposal"]
        try:
            parsed, proposal = self._validate(raw, state)
        except Exception as exc:
            append_jsonl(
                self.root / "proposal_rejections.jsonl",
                {
                    "round": state.get("round", 0) + 1,
                    "raw_proposal": raw,
                    "error_type": type(exc).__name__,
                    "actual_planner": state["actual_planner"],
                },
            )
            if self.mode == "llm" and self.study.get(
                "allow_deterministic_fallback", True
            ):
                update = self.baseline_plan(
                    state, "invalid_llm_proposal_" + type(exc).__name__
                )
                parsed, proposal = self._validate(update["raw_proposal"], state)
            else:
                return {
                    "terminal": True,
                    "stop_reason": "proposal_rejected",
                    "proposal": None,
                }
        self.memory.record_next_plan(
            {
                "raw_proposal": raw,
                "validated_proposal": proposal.to_dict() if proposal else None,
                "actual_planner": update.get("actual_planner", state["actual_planner"]),
                "fallback_reason": update.get(
                    "fallback_reason", state.get("fallback_reason")
                ),
            }
        )
        return {
            **update,
            "proposal": proposal.to_dict() if proposal else None,
            "terminal": proposal is None,
            "stop_reason": parsed.rationale if proposal is None else None,
        }

    def skill_executor(self, state):
        p = ExperimentProposal.from_dict(state["proposal"])
        self.tools.current = p.to_dict()
        self.tools.deadline = min(self.remaining(), self.limits.max_experiment_seconds)
        if self.tools.deadline <= 0:
            raise RuntimeError("Wall budget expired before numerical dispatch")
        tool = {
            "rule": "rule_scheduling",
            "cpsat": "cpsat_optimization",
            "rl": "rl_policy_evaluation",
        }[p.proposed_method]
        call = self.tools.invoke(tool, {"scenario_id": p.scenario_id, **p.parameters})
        if not call["ok"]:
            raise RuntimeError(
                "Typed numerical tool failed before producing an outcome"
            )
        pending = {
            "global_round": state.get("round", 0) + 1,
            "round": 0,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "proposal": p.to_dict(),
            "raw_llm_proposal": state.get("original_llm_proposal")
            if self.mode == "llm"
            else None,
            "actual_planner": state["actual_planner"],
            "fallback_reason": state.get("fallback_reason"),
            "planner_call": state.get("planner_call"),
            "observed_analysis": state["analyses"][p.scenario_id],
            "result": call["output"],
            "next_plan": None,
            "tool": tool,
        }
        return {
            "pending": pending,
            "cp_allocated_seconds": state.get("cp_allocated_seconds", 0)
            + (p.parameters["max_seconds"] if p.proposed_method == "cpsat" else 0),
        }

    def mathematical_verifier(self, state):
        row = json.loads(json.dumps(state["pending"]))
        p = row["proposal"]
        call = self.tools.invoke(
            "constraint_verification",
            {"scenario_id": p["scenario_id"], "experiment_id": p["experiment_id"]},
        )
        if not call["ok"]:
            verification = {
                "valid": False,
                "complete": False,
                "issues": ["graph_verification_error"],
                "independent_replay_valid": False,
            }
        else:
            verification = call["output"]
        row["result"]["verification"] = verification
        row["result"]["wall_seconds"] += call["wall_seconds"]
        self.tools.results[p["experiment_id"]] = row["result"]
        return {"pending": row}

    def result_analyzer(self, state):
        row = json.loads(json.dumps(state["pending"]))
        p = row["proposal"]
        prior = best_row(self.memory.histories[p["scenario_id"]].history)
        call = self.tools.invoke(
            "experiment_comparison",
            {
                "scenario_id": p["scenario_id"],
                "experiment_id": p["experiment_id"],
                "incumbent_id": prior["proposal"]["experiment_id"] if prior else None,
            },
        )
        if not call["ok"]:
            raise RuntimeError("Numerical comparison failed")
        row.update(call["output"])
        row["best_so_far_seconds"] = (
            row["result"]["metrics"].get("makespan_seconds")
            if row["acceptance"]["accepted"]
            else prior["best_so_far_seconds"]
            if prior
            else None
        )
        return {"pending": row}

    def research_reflection(self, state):
        row = json.loads(json.dumps(state["pending"]))
        reflection = None
        if self.mode == "llm":
            try:
                context = {
                    **self.planner_context(state),
                    "latest_result": {
                        "experiment_id": row["proposal"]["experiment_id"],
                        "proposal": row["proposal"],
                        "result": row["result"],
                        "acceptance": row["acceptance"],
                        "analysis": row["analysis"],
                    },
                    "instruction": "Explain this verified result and propose the next testable hypothesis. "
                    "The next planner may revise your proposal using the updated budget.",
                }
                raw, call = self.client.call(
                    "ResearchReflection", context, ResearchReflection, self.remaining()
                )
                reflection = ResearchReflection.model_validate(raw).model_dump()
                row["reflection_call"] = {
                    k: call.get(k)
                    for k in [
                        "call_id",
                        "model",
                        "status",
                        "http_status",
                        "evidence_source",
                        "usage",
                    ]
                }
            except Exception as exc:
                row["reflection_error"] = type(exc).__name__
        row["llm_reflection"] = reflection
        return {"pending": row, "reflection": reflection, "last_hypothesis": reflection}

    def research_memory(self, state):
        row = json.loads(json.dumps(state["pending"]))
        row["elapsed_seconds"] = self.elapsed()
        self.memory.commit(row)
        print(
            f"{self.mode} round={row['global_round']} scenario={row['proposal']['scenario_id']} "
            f"planner={row['actual_planner']} method={row['proposal']['proposed_method']} "
            f"verified={row['result']['verification']['valid']} "
            f"makespan={row['result']['metrics'].get('makespan_seconds')}",
            flush=True,
        )
        return {
            "round": row["global_round"],
            "history": json.loads(json.dumps(self.memory.records)),
            "pending": None,
        }

    def termination_controller(self, state):
        reason = state.get("stop_reason") if state.get("terminal") else None
        if state.get("round", 0) >= self.limits.max_rounds:
            reason = "max_rounds"
        elif self.remaining() < 3:
            reason = "total_active_wall_budget_exhausted"
        elif self.mode == "llm":
            usage = self.client.totals()
            if (
                usage["calls"] >= self.limits.max_llm_calls
                or usage["budget_charged_tokens"] >= self.limits.max_total_tokens
                or usage["budget_charged_usd"] >= self.limits.max_api_usd
            ):
                reason = "llm_call_token_or_fee_budget_exhausted"
        return {"terminal": bool(reason), "stop_reason": reason}

    def run(self, *, resume=False, pause_after=None):
        if resume:
            snapshot = self.graph.get_state(self.graph_config)
            if not snapshot.values:
                raise ValueError("No persistent graph checkpoint for resume")
            self.prior_elapsed = snapshot.values.get("elapsed_seconds", 0)
            if snapshot.values.get("round", 0) != len(self.memory.records):
                raise ValueError("Checkpoint and ResearchMemory boundary differ")
            state = snapshot.values
            if not snapshot.next:
                return self.summarize(state, state.get("stop_reason", "finished"))
            value = None
        else:
            value = {
                "round": 0,
                "cursor": 0,
                "elapsed_seconds": 0.0,
                "cp_allocated_seconds": 0.0,
                "history": [],
                "terminal": False,
                "stop_reason": None,
            }
        while True:
            state = self.graph.invoke(value, self.graph_config)
            if state.get("terminal"):
                return self.summarize(state, state["stop_reason"])
            if pause_after and state.get("round", 0) >= pause_after:
                return self.summarize(state, "paused_at_experiment_boundary")
            value = None

    def summarize(self, state, stop_reason):
        from .reporting import publish_session

        return publish_session(
            self.root,
            self.memory.records,
            self.mode,
            self.limits,
            self.client.totals(),
            self.elapsed(),
            stop_reason,
        )

    def close(self):
        self.connection.close()
