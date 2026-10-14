"""Closed, value-only LLM schemas and authoritative server-side admission."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wafer_sched.agent.planner import estimated_cost
from wafer_sched.agent.schemas import ExperimentProposal


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlannerProposal(ClosedModel):
    action: Literal["experiment", "stop"]
    scenario_id: str | None
    method: Literal["rule", "cpsat", "rl"] | None
    parameters: dict = Field(
        description='Exact method inputs only: rule uses {"policy": an allowed rule}; cpsat uses {"max_seconds": an allowed numeric budget}; rl uses {"model_id": an allowed existing model ID}. No other keys.'
    )
    rationale: str = Field(min_length=1, max_length=2000)
    hypothesis: str = Field(min_length=1, max_length=2000)
    expected_effect: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(
        max_length=100,
        description="Existing experiment_id values from supplied history only; use [] when no history exists. Do not put analysis text, static facts, measurements or invented IDs here.",
    )

    @model_validator(mode="after")
    def check_action(self):
        if self.action == "stop":
            if (
                self.scenario_id is not None
                or self.method is not None
                or self.parameters
            ):
                raise ValueError(
                    "Stop must have null scenario/method and empty parameters"
                )
        elif not self.scenario_id or self.method is None:
            raise ValueError("Experiment requires an allowed scenario and method")
        return self


class ResearchReflection(ClosedModel):
    explanation: str = Field(min_length=1, max_length=3000)
    failure_explanation: str = Field(max_length=2000)
    testable_hypothesis: str = Field(min_length=1, max_length=2000)
    next_proposal: PlannerProposal


class Limits(ClosedModel):
    max_rounds: int = Field(default=16, ge=1, le=100)
    total_seconds: float = Field(default=600.0, gt=0, le=3600)
    max_experiment_seconds: float = Field(default=40.0, gt=0, le=120)
    max_decisions: int = Field(default=4096, gt=0, le=20000)
    max_llm_calls: int = Field(default=36, ge=1, le=100)
    max_total_tokens: int = Field(default=120000, ge=100, le=1000000)
    max_api_usd: float = Field(default=0.20, gt=0, le=10)
    max_cp_seconds_total: float = Field(default=60.0, gt=0, le=300)
    minimum_real_llm_rounds: int = Field(default=5, ge=1, le=100)


def validate_proposal(
    raw,
    *,
    scenarios,
    histories,
    candidates,
    remaining,
    max_experiment_seconds,
    next_round,
    cp_remaining,
):
    proposal = PlannerProposal.model_validate(raw)
    known = {
        r["proposal"]["experiment_id"] for rows in histories.values() for r in rows
    }
    if not set(proposal.evidence) <= known:
        raise ValueError("Unknown evidence identifier")
    if proposal.action == "stop":
        return proposal, None
    if proposal.scenario_id not in scenarios:
        raise ValueError("Scenario not in the development allowlist")
    method, parameters = proposal.method, proposal.parameters
    # Cost estimates and IDs are supplied by the server, never trusted to the LLM.
    estimate = estimated_cost(method, parameters)
    experiment = ExperimentProposal(
        f"round-{next_round:03d}",
        proposal.scenario_id,
        method,
        parameters,
        proposal.hypothesis,
        proposal.evidence,
        estimate,
        proposal.rationale,
    )
    local_history = histories[proposal.scenario_id]
    # The original schema limits local evidence. Cross-scenario citations are checked
    # above; use a local view solely to apply its original numerical restrictions.
    local_ids = {r["proposal"]["experiment_id"] for r in local_history}
    local_copy = {
        **experiment.to_dict(),
        "evidence_from_history": [eid for eid in proposal.evidence if eid in local_ids],
    }
    ExperimentProposal.from_dict(local_copy).validate_context(
        proposal.scenario_id,
        local_history,
        candidates[proposal.scenario_id],
        remaining,
        max_experiment_seconds,
    )
    if method == "cpsat" and parameters["max_seconds"] > cp_remaining:
        raise ValueError("Cumulative CP search allocation exhausted")
    return proposal, experiment
