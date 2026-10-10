"""Feedback-dependent proposals; LLM only chooses within an executable whitelist."""

from dataclasses import dataclass
import json
import os

from .feedback import best_row
from .schemas import ExperimentProposal


@dataclass
class PlanningDecision:
    proposal: ExperimentProposal | None
    reason: str
    actual_planner: str
    fallback_reason: str | None = None


def estimated_cost(method, parameters):
    # Conservative admission estimates, never presented as measured cost.
    return parameters["max_seconds"] + 3.0 if method == "cpsat" else (10.0 if method == "rl" else 3.0)


class DeterministicPlanner:
    name = "DeterministicPlanner"

    def propose(self, *, scenario_id, history, analysis, candidates, remaining, max_experiment_seconds,
                recalled_memories=None):
        known = {ExperimentProposal.from_dict(row["proposal"]).signature for row in history}
        evidence = [row["proposal"]["experiment_id"] for row in history]
        incumbent = best_row(history)
        def offer(method, parameters, reason):
            proposal = ExperimentProposal(f"round-{len(history) + 1:03d}", scenario_id, method,
                parameters, reason, evidence, estimated_cost(method, parameters), reason)
            if proposal.signature in known or proposal.estimated_budget > min(remaining, max_experiment_seconds):
                return None
            return PlanningDecision(proposal, reason, self.name)
        def rules(names, reason):
            for name in names:
                if name in candidates["rules"]:
                    decision = offer("rule", {"policy": name}, reason)
                    if decision:
                        return decision
            return None
        if not history:
            return rules(["fifo"], "No verified history: establish the FIFO physical baseline") or PlanningDecision(
                None, "baseline_not_available_or_budget_exhausted", self.name)
        if any(row["result"].get("solver") and row["result"]["verification"]["valid"]
               and row["result"]["solver"]["status"] == "OPTIMAL"
               and not row["result"]["solver"]["restricted_model"] for row in history):
            return PlanningDecision(None, "verified_global_optimum_of_supported_static_instance", self.name)
        if incumbent is None:
            decision = rules(["spt", "ect", "adaptive", "bottleneck"],
                             "All previous attempts failed verification: try a distinct legal-catalogue rule")
            return decision or PlanningDecision(None, "no_verified_candidate_and_no_safe_remaining_rule", self.name)
        rule_history = [row for row in history if row["proposal"]["proposed_method"] == "rule"]
        rl_history = [row for row in history if row["proposal"]["proposed_method"] == "rl"]
        cp_history = [row for row in history if row["proposal"]["proposed_method"] == "cpsat"]
        block = analysis["blocking_to_processing_ratio"]
        busy = analysis["completion_window_robot_utilization"] or 0
        if len(rule_history) == 1:
            priority = ["bottleneck", "adaptive"] if block >= .2 else ["spt", "ect"]
            decision = rules(priority,
                f"FIFO event integrals: blocking/processing={block:.6g}, robot busy/span={busy:.6g}; test targeted rule")
            if decision:
                return decision
        if not rl_history:
            for identifier in candidates["models"]:
                decision = offer("rl", {"model_id": identifier},
                    f"Verified rule incumbent={analysis['current_best_seconds']:g}s, blocking ratio={block:.6g}; "
                    "test a validation-selected compatible pretrained policy; no retraining")
                if decision:
                    return decision
        if not cp_history:
            for budget in sorted(candidates["cp_budgets"]):
                decision = offer("cpsat", {"max_seconds": budget},
                    f"Current verified incumbent={analysis['current_best_seconds']:g}s; use it as validated CP hint "
                    "to seek a better schedule and a proof bound")
                if decision:
                    return decision
        if cp_history:
            latest = cp_history[-1]
            solver = latest["result"].get("solver") or {}
            status, gap = solver.get("status"), solver.get("relative_gap")
            budget = latest["proposal"]["parameters"]["max_seconds"]
            stagnant = (len(cp_history) >= 2 and not cp_history[-1]["acceptance"]["improves_incumbent"]
                        and not cp_history[-2]["acceptance"]["improves_incumbent"])
            if stagnant:
                for identifier in candidates["models"]:
                    decision = offer("rl", {"model_id": identifier},
                        f"Two CP attempts did not improve Makespan; latest status={status}, gap={gap}; "
                        "test another independently trained seed before spending a larger proof budget")
                    if decision:
                        return decision
                decision = rules(["ect", "spt", "adaptive", "bottleneck"],
                    f"CP improvement stalled and compatible RL candidates exhausted; robot busy/span={busy:.6g}; "
                    "use a cheap distinct rule to check order sensitivity")
                if decision:
                    return decision
            if status == "UNKNOWN" or (status == "FEASIBLE" and gap is not None and gap > .01):
                for higher in sorted(b for b in candidates["cp_budgets"] if b > budget):
                    decision = offer("cpsat", {"max_seconds": higher},
                        f"CP status={status}, gap={gap}, lower bound={solver.get('best_bound_seconds')}; "
                        f"remaining budget={remaining:.4g}s admits the next proof-search budget")
                    if decision:
                        return decision
        decision = rules(["ect", "spt", "adaptive", "bottleneck"],
                         f"No affordable useful CP escalation; verify another cheap rule against {analysis['current_best_seconds']:g}s")
        return decision or PlanningDecision(None, "candidate_space_exhausted_or_no_affordable_nonduplicate", self.name)


class CPBudgetPlanner(DeterministicPlanner):
    name = "CPBudgetPlanner"

    def propose(self, **context):
        history = context["history"]
        if not history:
            return super().propose(**context)
        cp = [row for row in history if row["proposal"]["proposed_method"] == "cpsat"]
        if cp and (cp[-1]["result"].get("solver") or {}).get("status") == "OPTIMAL" and cp[-1]["result"]["verification"]["valid"]:
            return PlanningDecision(None, "verified_supported_instance_optimum", self.name)
        if len(cp) >= 2:
            before = cp[-2]["result"].get("solver") or {}
            after = cp[-1]["result"].get("solver") or {}
            bound_gain = (after.get("best_bound_seconds") or 0) - (before.get("best_bound_seconds") or 0)
            objective_gain = cp[-1]["acceptance"]["improves_incumbent"]
            if not objective_gain and bound_gain <= 1e-7:
                return PlanningDecision(None, "two_cp_budgets_no_incumbent_or_bound_gain", self.name)
        latest_budget = cp[-1]["proposal"]["parameters"]["max_seconds"] if cp else 0
        for budget in sorted(context["candidates"]["cp_budgets"]):
            if budget <= latest_budget:
                continue
            estimated = estimated_cost("cpsat", {"max_seconds": budget})
            if estimated <= min(context["remaining"], context["max_experiment_seconds"]):
                solver = (cp[-1]["result"].get("solver") or {}) if cp else {}
                reason = (f"Previous CP status={solver.get('status')}, gap={solver.get('relative_gap')}, "
                          f"bound={solver.get('best_bound_seconds')}; remaining={context['remaining']:.4g}s; "
                          "increase budget only while useful")
                proposal = ExperimentProposal(f"round-{len(history)+1:03d}", context["scenario_id"], "cpsat",
                    {"max_seconds": budget}, reason[:2000], [r["proposal"]["experiment_id"] for r in history],
                    estimated, reason[:2000])
                return PlanningDecision(proposal, reason, self.name)
        return PlanningDecision(None, "no_affordable_larger_cp_budget", self.name)


class FixedOrderPlanner:
    """Explicit nonadaptive ablation; never described as autonomous planning."""
    name = "FixedOrderPlanner"

    def __init__(self, order):
        self.order = order

    def propose(self, **context):
        index = len(context["history"])
        if index >= len(self.order):
            return PlanningDecision(None, "fixed_order_exhausted", self.name)
        method, parameters = self.order[index]
        reason = "Predeclared fixed-order ablation; selection ignores measured feedback"
        proposal = ExperimentProposal(f"round-{index+1:03d}", context["scenario_id"], method, parameters,
            reason, [], estimated_cost(method, parameters), reason)
        if proposal.estimated_budget > min(context["remaining"], context["max_experiment_seconds"]):
            return PlanningDecision(None, "fixed_next_candidate_not_affordable", self.name)
        return PlanningDecision(proposal, reason, self.name)


class SemanticaLLMPlanner:
    name = "SemanticaLLMPlanner"

    def __init__(self, *, allow_llm_egress=False, transport=None):
        self.allow_llm_egress = allow_llm_egress
        self.transport = transport
        self.fallback = DeterministicPlanner()

    def propose(self, **context):
        fallback_reason = None
        if not self.allow_llm_egress:
            fallback_reason = "research_egress_not_enabled"
        elif not all(os.environ.get(key) for key in ("ASSISTANT_LLM_BASE_URL", "ASSISTANT_LLM_API_KEY", "ASSISTANT_LLM_MODEL")):
            fallback_reason = "llm_configuration_unavailable"
        else:
            try:
                from wafer_sched.infrastructure.model_transport import model_completion
                from wafer_sched.infrastructure.model_endpoint import validated_model_base_url
                body = {"model": os.environ["ASSISTANT_LLM_MODEL"], "temperature": 0,
                    "messages": [{"role": "system", "content":
                        "Return only one JSON ExperimentProposal with exactly these fields: "
                        + ', '.join(ExperimentProposal.__dataclass_fields__)
                        + ". Choose only allowed methods/parameters. Do not emit code or measured results. "
                        "Use round-NNN for the next experiment_id. Cite only provided historical experiment IDs."},
                        {"role": "user", "content": json.dumps({
                            "scenario_id": context["scenario_id"], "next_round": len(context["history"])+1,
                            "allowed": {"rules": context["candidates"]["rules"],
                                        "cp_budgets": context["candidates"]["cp_budgets"],
                                        "model_ids": list(context["candidates"]["models"])},
                            "analysis": context["analysis"], "remaining_seconds": context["remaining"],
                            "history": [{"experiment_id": r["proposal"]["experiment_id"],
                                "method": r["proposal"]["proposed_method"], "parameters": r["proposal"]["parameters"],
                                "valid": r["result"]["verification"]["valid"],
                                "makespan": r["result"]["metrics"].get("makespan_seconds"),
                                "solver_status": (r["result"].get("solver") or {}).get("status")}
                                for r in context["history"]]}, ensure_ascii=False)}]}
                completion = (self.transport or model_completion)(
                    validated_model_base_url(os.environ["ASSISTANT_LLM_BASE_URL"]),
                    os.environ["ASSISTANT_LLM_API_KEY"], body)
                content = completion["choices"][0]["message"]["content"]
                if not isinstance(content, str) or len(content) > 8000:
                    raise ValueError("Invalid proposal size")
                proposal = ExperimentProposal.from_dict(json.loads(content))
                proposal.validate_context(context["scenario_id"], context["history"], context["candidates"],
                                          context["remaining"], context["max_experiment_seconds"])
                return PlanningDecision(proposal, "validated_llm_proposal", self.name)
            except Exception as exc:
                fallback_reason = "llm_failure_" + type(exc).__name__
        decision = self.fallback.propose(**context)
        decision.fallback_reason = fallback_reason
        return decision
