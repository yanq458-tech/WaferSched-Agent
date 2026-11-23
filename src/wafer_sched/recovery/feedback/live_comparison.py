"""Matched, explicitly paid rerun on the archived final holdout (no answer inputs)."""

import argparse
import json
import os
import random
import shutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, TimeoutError
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import ValidationError
from ...langgraph_agent.llm import LLMClient, LLMSettings, LLMUnavailable
from ...langgraph_agent.schemas import ClosedModel, Limits
from .. import holdout
from ..continuation import Continuation
from ..evidence_study import save
from ..policy_retest import pin
from ..terminal_diagnostics import profile
from .async_advice import StallAdvisor
from .goal_advice import GoalAdvisor
from .policy import solve
from .study import sources


ARCHIVE = Path("results/recovery/feedback-study/final-holdout")
METHODS = ["plain", "agent", "deepseek"]


class Decision(ClosedModel):
    target: Literal["upper", "middle", "zero"]
    tool: Literal["grid_then_exact", "exact"]


class TimedChoice:
    def __init__(self, client, pool):
        self.client, self.pool = client, pool

    def __call__(self, context, deadline):
        start = perf_counter()
        context = {**context, "goal": "Prove the latest feasible repair or tighten the open interval.",
                   "instruction": "Select one target from options. -1 lower means no feasible witness. "
                   "grid_then_exact tries a cheap sufficient witness then exact CP if time allows. "
                   "exact directly checks fixed-delay feasibility. Only one planning request is allowed."}
        # Run receipt collection separately. After the deadline no response can reach a solver.
        future = self.pool.submit(self.client.call, "recovery_first_probe", context, Decision, 15)
        choice = None
        try:
            raw, _ = future.result(timeout=max(0, deadline - perf_counter()))
            parsed = Decision.model_validate(raw)
            if parsed.target not in context["options"]:
                raise ValueError("target unavailable")
            choice, outcome = parsed, "applied"
        except TimeoutError:
            outcome = "expired"
        except (LLMUnavailable, ValidationError, ValueError):
            outcome = "invalid_or_unavailable"
        if perf_counter() >= deadline:
            choice, outcome = None, "expired"
        return choice, dict(tool="deepseek_first_probe", outcome=outcome,
                            decision=choice.model_dump() if choice else None,
                            waited_seconds=perf_counter()-start)


def lane(root, items, core, budget, local_first, objectives):
    pin(core)
    settings = LLMSettings.from_local(".env", {"max_output_tokens": 96, "timeout_seconds": 15})
    if not settings.configured or settings.model != "deepseek-flash" or settings.base_url.rstrip("/") not in {
        "https://api.deepseek.com", "https://api.deepseek.com/v1"
    }:
        raise ValueError("Official DeepSeek Flash configuration required")
    for idx, item in items:
        name = item["case"]
        path = root / "inputs" / (name + ".json")
        assert holdout.digest(path) == item["sha256"]
        order = METHODS[idx % 3:] + METHODS[:idx % 3]
        if idx // 3 % 2:
            order.reverse()
        for rep in (0, 1):
            statuses = set()
            for method in order:
                log = root / "receipts" / f"b{budget}" / name / f"{rep}.jsonl"
                client = LLMClient(settings, Limits(max_llm_calls=1, max_total_tokens=6000,
                                                     max_api_usd=0.003), log) if method == "deepseek" else None
                with ThreadPoolExecutor(max_workers=1) as pool:
                    planner = TimedChoice(client, pool) if client is not None and not local_first else None
                    advisor = StallAdvisor(client, pool) if client is not None and local_first and not objectives and budget > 1 else None
                    goal_advisor = GoalAdvisor(client, pool) if client is not None and objectives and budget > 1 else None

                    def runner(case, mode, seconds):
                        return solve(case, seconds, "agent" if mode == "deepseek" else mode,
                                     first_probe=planner, advisor=advisor, goal_advisor=goal_advisor)

                    record = profile(Continuation.from_dict(json.loads(path.read_bytes())), method,
                                     budget, runner=runner)
                # Only receipt drain is outside the timed call. No proof/schedule is updated here.
                monitor = goal_advisor or advisor
                if monitor is not None:
                    record["async_accounting"] = monitor.accounting()
                record.pop("trace")
                record.update(case=name, repeat=rep, core=core, order=order.copy())
                if client is not None:
                    record["api"] = client.totals()
                save(root / f"b{budget}" / name / f"{rep}-{method}.json", record)
                statuses.add(record["metrics"]["status"])
            if budget == 30 and len(statuses) == 1:
                break
            order.reverse()


def benchmark(root, local_first=True, objectives=False):
    root.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(ARCHIVE / "manifest.json", root / "manifest.json")
    shutil.copytree(ARCHIVE / "inputs", root / "inputs")
    freeze = json.loads((ARCHIVE / "freeze.json").read_bytes())
    assert holdout.digest(root / "manifest.json") == freeze["manifest"]
    protocol = dict(methods=METHODS, budgets=[1, 30], internal_fraction=0.85, cores=holdout.CORES,
                    seed=6815033, one_second_repeats=2, repeat_30="only when first statuses disagree",
                    strategy="feedback_objectives" if objectives else "local_first_async" if local_first else "blocking_first_probe",
                    python_hash_seed=os.getenv("PYTHONHASHSEED"),
                    goal_source=holdout.digest(Path(__file__).with_name("goal_advice.py")),
                    llm=("1s local; after completed exact query, one async choice of objective, advice never sets bounds" if objectives else "1s purely local; 30s at most one background request after a failed local "
                         "grid probe and open interval, continue exact query, discard stale advice"
                         if local_first else "one blocking call at first unresolved probe"),
                    deadline="original wall-clock scoring; expired replies discarded, usage retained",
                    input_manifest=freeze["manifest"], historical_commit="ce12de6", source=sources(),
                    experiment_sha256=holdout.digest(Path(__file__)),
                    advisor_sha256=holdout.digest(Path(__file__).with_name("async_advice.py")))
    save(root / "protocol.json", protocol)
    save(root / "freeze.json", {"manifest":freeze["manifest"], "protocol":holdout.digest(root/"protocol.json")})
    items = json.loads((root/"manifest.json").read_bytes())
    random.Random(protocol["seed"]).shuffle(items)
    tasks = list(enumerate(items))
    for budget in (1, 30):
        with ProcessPoolExecutor(max_workers=len(holdout.CORES)) as pool:
            futures = [pool.submit(lane, root, tasks[i::len(holdout.CORES)], core, budget, local_first, objectives)
                       for i, core in enumerate(holdout.CORES)]
            for future in futures:
                future.result()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--live", action="store_true", required=True)
    ap.add_argument("--blocking-first-probe", action="store_true", help="reproduce the previous comparison")
    ap.add_argument("--feedback-objectives", action="store_true")
    args = ap.parse_args()
    if args.feedback_objectives and args.blocking_first_probe:
        ap.error("choose a single live policy")
    benchmark(args.out, local_first=not args.blocking_first_probe, objectives=args.feedback_objectives)
