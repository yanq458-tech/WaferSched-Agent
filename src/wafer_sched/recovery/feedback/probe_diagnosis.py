"""Replay a capacity subproblem, or audit the seven archived midpoint suggestions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from ortools.sat.python import cp_model
from ..terminal_exact import terminal_domain
from ..continuation import Continuation
from ..conflict_evidence import best_bound
from ..holdout_review import load
from ..policy_retest import write_csv, pin
from .capacity import bound


def capacity_replay(root, name, seconds, min_tick=None):
    pin(2)
    p, prefix = Continuation.from_dict(load(root / "inputs" / (name + ".json"))).prepare()
    domain, cap = terminal_domain(p), best_bound(p)["upper_tick"]
    fields = dict(hash_seed=os.environ.get("PYTHONHASHSEED"), case=name, cap=cap, ticks_per_second=p.scale,
                  offset=prefix["offset"])
    original = cp_model.CpSolver.solve
    def capture(solver, model, *args, **kwargs):
        if min_tick is not None:
            ix, = [i for i,v in enumerate(model.proto.variables) if v.name == "repair"]
            model.clear_objective()
            model.add(model.get_int_var_from_proto_index(ix) >= min_tick)
        fields["model_sha256"] = hashlib.sha256(model.proto.SerializeToString(deterministic=True)).hexdigest()
        return original(solver, model, *args, **kwargs)
    with patch.object(cp_model.CpSolver, "solve", capture):
        _, event = bound(p, domain, cap, perf_counter()+seconds)
    if min_tick is not None:
        event.pop("upper_tick")  # No objective bound in a satisfaction problem.
        fields["require_at_least_tick"] = min_tick
    return {**fields, **event}


def midpoint_rows(root):
    rows = []
    for file in sorted((root / "receipts/b30").glob("*/0.jsonl")):
        call = load(file)
        ctx = json.loads(call["request"]["messages"][-1]["content"])
        choice = json.loads(call["response"]["choices"][0]["message"]["content"])
        name = file.parent.name
        run = load(root / "b30" / name / "0-deepseek.json")
        ts = run["evidence"]["trace"]
        event = next(e for e in ts if e["tool"] == "deepseek_async_advice")
        q = ctx["options"][choice["target"]]
        idx = next((i for i,e in enumerate(ts) if e.get("reason") == "async_deepseek_middle"), None)
        grid = exact = {}
        if idx is not None:
            grid, exact = ts[idx+1:idx+3]
            assert grid["tool"] == "grid_satisfaction" and exact["tool"] == "strengthened_fixed_repair"
            assert q == exact["repair_tick"] == grid["repair_tick"]
        rows.append(dict(case=name, offered=",".join(ctx["options"]), active_tick=ctx["active_exact_query_tick"],
                         lower_tick=ctx["lower_tick"], upper_tick=ctx["upper_tick"], recommendation=choice["target"],
                         tool=choice["tool"], suggested_seconds=q/ctx["ticks_per_second"], outcome=event["outcome"],
                         grid_status=grid.get("status"), grid_attempts=grid.get("attempts",0),
                         cp_status=exact.get("status"), cp_search_seconds=exact.get("seconds",0)))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--case")
    ap.add_argument("--seconds",type=float,default=1.3)
    ap.add_argument("--min-delay-ticks", type=int)
    ap.add_argument("--out",type=Path)
    args = ap.parse_args()
    if args.case:
        print(json.dumps(capacity_replay(args.root,args.case,args.seconds,args.min_delay_ticks)))
    else:
        write_csv(args.out,midpoint_rows(args.root))
