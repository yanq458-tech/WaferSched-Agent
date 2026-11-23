"""Nonblocking, one-shot advice for an unresolved local recovery search."""

from time import perf_counter
from typing import Literal

from pydantic import ValidationError

from ...langgraph_agent.llm import LLMUnavailable
from ...langgraph_agent.schemas import ClosedModel


class Advice(ClosedModel):
    target: Literal["upper", "middle", "zero"]
    tool: Literal["grid_then_exact", "exact"]


class StallAdvisor:
    def __init__(self, client, executor):
        self.client = client
        self.executor = executor
        self.future = None
        self.event = None
        self.request_interval = []
        self.local_intervals = []

    def on_stall(self, lo, hi, asked, active, wafers, scale, attempts, deadline):
        left = deadline - perf_counter()
        if self.future is not None or left < 2 or hi <= lo or not attempts:
            return
        targets = {"upper": hi, "middle": (hi + max(lo, 0) + 1) // 2, "zero": 0}
        options = {k: q for k, q in targets.items() if lo < q <= hi and q not in asked}
        if not options:
            return
        self.event = dict(tool="deepseek_async_advice", trigger="local_grid_no_witness",
                          lower_tick=lo, upper_tick=hi, active_tick=active, grid_attempts=attempts,
                          options=options, outcome="unused_at_stop", decision=None, waited_seconds=0)
        context = dict(wafers=wafers, ticks_per_second=scale, lower_tick=lo, upper_tick=hi,
                       active_exact_query_tick=active, failed_grid_attempts=attempts, options=options,
                       remaining_seconds=round(left, 3),
                       instruction="Local search continues at the active repair tick. Choose one listed target "
                       "for the NEXT probe and its tool; -1 means no verified lower bound. "
                       "Prefer a query that could close the interval or improve a bound. "
                       "grid_then_exact attempts a constructive witness before exact search.")

        self.submit("recovery_after_local_stall", context, Advice, left)

    def submit(self, stage, context, schema, left):
        def request():
            self.request_interval.append(perf_counter())
            try:
                return self.client.call(stage, context, schema, min(15, left))
            finally:
                self.request_interval.append(perf_counter())

        self.future = self.executor.submit(request)

    def record_local(self, start, end, tick):
        if self.future is not None:
            self.local_intervals.append((start, end, tick))

    def poll(self, lo, hi, asked, deadline):
        if self.future is None or self.event["outcome"] != "unused_at_stop" or not self.future.done():
            return None
        if perf_counter() >= deadline:
            return None
        try:
            raw, _ = self.future.result()
            choice = Advice.model_validate(raw)
            q = self.event["options"][choice.target]
        except (LLMUnavailable, ValidationError, ValueError, KeyError):
            self.event["outcome"] = "invalid_or_unavailable"
            return None
        self.event["decision"] = choice.model_dump()
        if q in asked or not lo < q <= hi:
            self.event["outcome"] = "stale"
            return None
        self.event["outcome"] = "applied"
        self.event["selected_tick"] = q
        return q, choice

    def accounting(self):
        # Only called after the worker is joined. These measurements never enter search.
        if not self.request_interval:
            return {}
        begin, end = self.request_interval
        return dict(request_seconds=end-begin, local_exact_overlap_seconds=sum(
            max(0, min(b, end) - max(a, begin)) for a, b, _ in self.local_intervals),
            exact_searches_during_request=[q for a,b,q in self.local_intervals if min(end,b)>max(begin,a)])
