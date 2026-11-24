"""Learn the chance that a fixed-repair probe produces evidence, from archived decisions."""
from collections import Counter
from math import exp
from pathlib import Path
from time import perf_counter
import json
import numpy as np

from ..continuation import Continuation
from ..evidence_study import save
from ..holdout import digest
from ..terminal_exact import terminal_domain
from .replay_state import FeedbackIncident

ARCHIVES = tuple(Path("results/recovery/feedback-study") / name for name in ("holdout", "final-holdout"))
GOALS = ("find_witness", "tighten_upper")
FEATURES = ("wip/24", "single_choice_fraction", "max_healthy_exclusive_fraction", "short_budget",
            "has_witness", "remaining_gap_seconds_per_wafer", "previous_query_count/6",
            "last_exact_unknown", "last_exact_infeasible")


def features(domain, failed, lo, hi, scale, short, trace):
    jobs = domain[0]
    single = Counter(j.choices[0][0] for j in jobs if len(j.choices) == 1)
    n = len(jobs)
    last = next((v["status"] for v in reversed(trace) if v["tool"] == "strengthened_fixed_repair"), "")
    count = sum(v["tool"] == "choose_second_method" for v in trace)
    return [n / 24, sum(single.values()) / n, max((v for k, v in single.items() if k != failed),
            default=0) / n, int(short), int(lo >= 0), (hi - max(0, lo)) / scale / n,
            count / 6, int(last == "UNKNOWN"), int(last == "INFEASIBLE")]


def dataset():
    rows, files = [], {}
    for root in ARCHIVES:
        for src in sorted((root / "inputs").glob("*.json")):
            case = Continuation.from_dict(json.loads(src.read_bytes()))
            p, _ = FeedbackIncident(**vars(case)).prepare()
            domain = terminal_domain(p)
            files[str(src)] = digest(src)
            for log in sorted(root.glob(f"b*/{src.stem}/*.json")):
                record = json.loads(log.read_bytes())
                if record.get("method") not in ("agent", "plain", "fixed"):
                    continue
                files[str(log)] = digest(log)
                trace = record["evidence"]["trace"]
                for i, v in enumerate(trace):
                    if v["tool"] != "choose_second_method":
                        continue
                    lo, hi, q = (v[k] for k in ("lower_tick", "upper_tick", "repair_tick"))
                    low = max(0, lo + 1)
                    if low == hi or q not in (low, hi):
                        continue
                    receipts = []
                    for event in trace[i+1:]:
                        if event["tool"] in ("choose_second_method", "prefix_capacity_relaxation"):
                            break
                        if event["tool"] in ("grid_satisfaction", "strengthened_fixed_repair") and event.get("repair_tick") == q:
                            receipts.append(event["status"])
                    if not receipts:
                        continue
                    goal = GOALS[int(q == hi)]
                    x = features(domain, p.failed_chamber, lo, hi, p.scale, log.parents[1].name == "b1", trace[:i])
                    success = any(s in ("WITNESS","FEASIBLE","OPTIMAL","INFEASIBLE") for s in receipts)
                    rows.append(dict(case=src.stem, source=log.as_posix(), event=i, goal=goal, x=x,
                                     outcome=int(success), receipts=receipts))
    return rows, files


def fit(rows):
    """Two ridge-logistic response models. Give each represented snapshot equal weight per goal."""
    models = {}
    for goal in GOALS:
        data = [r for r in rows if r["goal"] == goal]
        counts = Counter(r["case"] for r in data)
        x = np.array([[1, *r["x"]] for r in data])
        y = np.array([r["outcome"] for r in data])
        weights = np.array([1 / counts[r["case"]] for r in data])
        penalty = np.diag([0.1] + [1.] * len(FEATURES))
        beta = np.zeros(x.shape[1])
        for _ in range(40):
            prob = 1 / (1 + np.exp(-np.clip(x @ beta, -35, 35)))
            grad = x.T @ (weights * (prob - y)) + penalty @ beta
            curvature = x.T @ ((weights * prob * (1-prob))[:, None] * x) + penalty
            delta = np.linalg.solve(curvature, grad)
            beta -= delta
            if np.max(np.abs(delta)) < 1e-9:
                break
        models[goal] = beta.tolist()
    return models


def probability(coef, x):
    return 1 / (1 + exp(-max(-35, min(35, coef[0] + sum(a*b for a,b in zip(coef[1:], x, strict=True))))))


def train(root):
    rows, files = dataset()
    coefficients = fit(rows)
    errors, naive = [], []
    for case in sorted({r["case"] for r in rows}):
        tr = [r for r in rows if r["case"] != case]
        local = fit(tr)
        for r in rows:
            if r["case"] == case:
                sample = [v["outcome"] for v in tr if v["goal"] == r["goal"]]
                naive.append((sum(sample)/len(sample)-r["outcome"])**2)
                errors.append((probability(local[r["goal"]],r["x"])-r["outcome"])**2)
    save(root/"training.json",dict(inputs_and_logs=files, observations=rows))
    save(root/"model.json",dict(features=FEATURES, coefficients=coefficients, rows=len(rows),
         cases=len({v["case"] for v in rows}), actions={g:dict(n=sum(r["goal"]==g for r in rows),
         positive=sum(r["outcome"] for r in rows if r["goal"]==g)) for g in GOALS},
         leave_snapshot_out_brier=float(np.mean(errors)), unweighted_action_prior_brier=float(np.mean(naive))))


def selector(model):
    def select(domain, failed, lo, hi, scale, short, asked, trace, default):
        start = perf_counter()
        x = features(domain, failed, lo, hi, scale, short, trace)
        scores = {g:probability(model["coefficients"][g], x) for g in GOALS}
        candidates = {g:q for g,q in zip(GOALS,(max(0,lo+1),hi)) if q not in asked}
        goal = max(candidates, key=lambda g:(scores[g], candidates[g]==default)) if candidates else "fallback"
        q = candidates.get(goal, default)
        return q, dict(tool="learned_query", scores=scores, features=x, chosen=goal, tick=q,
                       default_tick=default, candidates=candidates, seconds=perf_counter()-start)
    return select
