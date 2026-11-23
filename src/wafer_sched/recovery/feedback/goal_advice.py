"""Ask for an objective only after local fixed-delay search has returned feedback."""

from time import perf_counter
from typing import Literal

from pydantic import Field, ValidationError

from ...langgraph_agent.llm import LLMUnavailable
from ...langgraph_agent.schemas import ClosedModel
from .async_advice import StallAdvisor


class Goal(ClosedModel):
    goal: Literal["find_witness", "tighten_upper", "keep_local"]
    reason: str = Field(min_length=1, max_length=180)


def parse_goal(raw):
    # Bound only the recorded explanation; it does not choose or validate a solver action.
    if isinstance(raw, dict) and isinstance(raw.get("reason"), str):
        raw = {**raw, "reason": raw["reason"][:180]}
    return Goal.model_validate(raw)


class GoalAdvisor(StallAdvisor):
    def after_query(self, lo, hi, q, trace, domain, scale, failed, deadline):
        left = deadline - perf_counter()
        if self.future is not None or lo >= hi or left < 2:
            return
        jobs, *_ = domain
        recent = [e for e in trace if e["tool"] in {
            "pilot_feedback","prefix_capacity_relaxation","grid_satisfaction","strengthened_fixed_repair"
        }][-5:]
        context = dict(wafers=len(jobs), ticks_per_second=scale,
                       mandatory_failed_loads=sum(all(c == failed for c,_ in j.choices) for j in jobs),
                       eligible_counts=sorted(len(j.choices) for j in jobs),
                       ready_range=[min(j.ready for j in jobs),max(j.ready for j in jobs)],
                       pick_deadline_range=[min(j.due for j in jobs),max(j.due for j in jobs)],
                       has_verified_schedule=lo >= 0, lower_tick=lo, upper_tick=hi, recent=recent,
                       remaining_seconds=round(left,3),
                       instruction="Choose the next objective using the completed solver feedback. "
                       "find_witness runs a diversified exact feasibility search at the smallest admissible "
                       "delay, or just above a verified lower bound. tighten_upper gives a time-limited "
                       "capacity relaxation more time if unresolved, then tests its current upper by exact CP. "
                       "keep_local delegates to the existing policy (capacity bound then constructive and exact "
                       "tests at the upper end). Local computation continues while you respond. If no evidence "
                       "supports an override, keep_local is valid. Give one short reason citing the feedback.")
        self.event = dict(tool="deepseek_goal", trigger="completed_local_query", active_tick=q,
                          lower_tick=lo, upper_tick=hi, outcome="unused_at_stop", waited_seconds=0, decision=None)
        self.submit("recovery_after_fixed_query", context, Goal, left)

    def take(self, deadline):
        if self.future is None or self.event["outcome"] != "unused_at_stop" or not self.future.done():
            return None
        if perf_counter() >= deadline:
            return None
        try:
            raw, _ = self.future.result()
            choice = parse_goal(raw)
        except (LLMUnavailable, ValueError, ValidationError):
            self.event["outcome"] = "invalid_or_unavailable"
            return None
        self.event["decision"] = choice.model_dump()
        self.event["outcome"] = "kept_local" if choice.goal == "keep_local" else "applied"
        return None if choice.goal == "keep_local" else choice.goal
