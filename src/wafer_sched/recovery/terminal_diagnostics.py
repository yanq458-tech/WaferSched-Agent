"""Reproduce separately timed phase profiles and controlled constraint relaxations."""

import argparse
from statistics import median
from collections import Counter
from contextlib import ExitStack
from dataclasses import replace
from functools import wraps
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from ortools.sat.python import cp_model

from . import direct, dispatch, solver, terminal_exact, tail_ranks, healthy_witness
from .conflict_evidence import best_bound
from .continuation import Continuation
from .evidence_study import ROOT, run_case, save
from .policy_retest import pin, read_case, write_csv

OUT = Path("results/recovery/terminal-proofs")
BASE = Path("results/recovery/hard-case-policy/paired30/runs")
METHODS = ("graph_legacy", "graph_policy", "graph_refined")


def profile(case, method, budget, *, runner=None, extra_phases=()):
    totals, counts, calls, active = Counter(), Counter(), [], []

    def wrap(module, name, phase, stack):
        original = getattr(module, name)

        @wraps(original)
        def timed(*args, **kwargs):
            start = perf_counter()
            active.append(0.0)
            try:
                result = original(*args, **kwargs)
                if phase == "cp_sat":
                    s = args[0]
                    calls.append(
                        dict(
                            status=s.status_name(result),
                            branches=s.num_branches,
                            conflicts=s.num_conflicts,
                        )
                    )
                return result
            finally:
                elapsed = perf_counter() - start
                child = active.pop()
                totals[phase] += elapsed - child
                counts[phase] += 1
                if active:
                    active[-1] += elapsed

        stack.enter_context(patch.object(module, name, timed))

    with ExitStack() as stack:
        for mod, name, phase in [
            (Continuation, "prepare", "snapshot"),
            (tail_ranks, "solve_rank", "rank_encode_extract"),
            (tail_ranks, "replay_recovery", "replay"),
            (tail_ranks, "replay_incident", "replay"),
            (healthy_witness, "replay_recovery", "replay"),
            (healthy_witness, "replay_incident", "replay"),
            (healthy_witness, "find_healthy_schedule", "construct"),
            (solver, "build_recovery_model", "build"),
            (direct, "build_recovery_model", "build"),
            (terminal_exact, "build", "build"),
            (cp_model.CpSolver, "solve", "cp_sat"),
            (solver, "replay_recovery", "replay"),
            (direct, "replay_recovery", "replay"),
            (dispatch, "replay_incident", "replay"),
            (direct, "replay_incident", "replay"),
            (terminal_exact, "replay_incident", "replay"),
            *extra_phases,
        ]:
            wrap(mod, name, phase, stack)
        row, evidence = run_case(case, method, budget, runner=runner)
    totals["other"] = row["wall_seconds"] - sum(totals.values())
    return dict(
        method=method,
        phases=dict(totals),
        counts=dict(counts),
        calls=calls,
        metrics=row,
        trace=evidence["trace"],
        **({"evidence": evidence} if runner is not None else {}),
    )


def relax(case, rows, name, seconds):
    p, prefix = case.prepare()
    domain = terminal_exact.terminal_domain(p)
    conflict = terminal_exact.workload(domain)
    if conflict:
        assert terminal_exact.verify_workload(p, conflict)
        return dict(conflict=conflict, scale=p.scale, offset=prefix["offset"])
    bound = terminal_exact.last_load_bound(p, domain)
    route = best_bound(p)
    # Fixed queries at immediate repair and at the previous route upper.
    for q in (0, route["upper_tick"]):
        for group in (
            "original",
            "no_source_deadlines",
            "no_terminal_residence",
            "no_inbound_hold",
        ):
            jobs, pick, place, travel = domain
            changes = {
                "no_source_deadlines": {"due": None},
                "no_terminal_residence": {"residence": None},
                "no_inbound_hold": {"hold_in": None},
                "original": {},
            }
            reduced = ([replace(j, **changes[group]) for j in jobs], pick, place, travel)
            bundle = terminal_exact.build(p, reduced, None)
            bundle.model.add(bundle.repair_variable == q)
            bundle.model.clear_objective()
            cp = cp_model.CpSolver()
            cp.parameters.random_seed = 1
            cp.parameters.max_time_in_seconds = seconds
            cp.parameters.num_search_workers = 1
            status = cp.solve(bundle.model)
            rows.append(
                dict(
                    case=name,
                    repair=q / p.scale,
                    relaxation=group,
                    status=cp.status_name(status),
                    branches=cp.num_branches,
                    seconds=cp.wall_time,
                )
            )
    profiles = []
    if bound:
        jobs, pick, place, travel = domain
        mandatory = next(j for j in jobs if j.wafer == bound["wafer"])
        values = []
        for j in jobs:
            if j == mandatory:
                continue
            allowed = [t + j.residence for c, t in j.choices if c != p.failed_chamber]
            if allowed:
                values.append(max(allowed))
        ranked = sorted(values, reverse=True)
        for k in range(bound["min_pending"], len(ranked) + 1):
            # Conditional on k or more healthy wafers awaiting pickup at the last source load.
            upper = mandatory.due - 2 * pick - 2 * travel - place
            upper += sum(ranked[:k]) // k - (k - 1) * (pick + place + 2 * travel)
            profiles.append(dict(pending_at_least=k, late_branch_upper_tick=upper))
    pending = terminal_exact.pending_conflict(p, domain)
    assert pending is None or terminal_exact.verify_pending(p, pending)
    return dict(
        last_load=bound,
        route=route,
        pending_profile=profiles,
        pending_conflict=pending,
        scale=p.scale,
        offset=prefix["offset"],
    )


def check_zero(case, seconds):
    """Independent of both arithmetic cuts. Restore every original source deadline."""
    p, prefix = case.prepare()
    domain = terminal_exact.terminal_domain(p)
    bundle = terminal_exact.build_zero(p, domain)
    cp = cp_model.CpSolver()
    cp.parameters.random_seed = 1
    cp.parameters.max_time_in_seconds = seconds
    cp.parameters.num_search_workers = 1
    status = cp.solve(bundle.model)
    row = dict(
        status=cp.status_name(status),
        branches=cp.num_branches,
        seconds=cp.wall_time,
        solver_limit=seconds,
        arithmetic_cuts=False,
    )
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        plan, check = solver.read_witness(p, bundle, cp, 0)
        assert check["valid"]
        out = dict(
            witness_repair_delay_seconds=prefix["offset"],
            makespan_seconds=prefix["offset"] + plan["makespan_tick"] / p.scale,
        )
        dispatch.replay_incident(case, prefix, out, {"verification": check})
        row.update(schedule=plan, verified=True)
    return row


def summarize(folder):
    from .confirm_regressions import flags
    from .policy_retest import PROVED, quality

    def read(path):
        return json.loads(path.read_bytes())

    manifest = read(ROOT / "manifest.json")
    certificates = read(folder / "certificates.json")
    detail, comparisons = [], []
    for budget in (1, 30):
        paired = folder / f"paired{budget}"
        secondary_file = paired / "secondary" / "results.json"
        secondary = read(secondary_file) if secondary_file.exists() else {}
        for item in manifest:
            name = item["case"]
            old_history = read(BASE / f"{name}-0-graph_policy.json")["metrics"]
            archive = [old_history]
            for seconds in (1, 30):
                archive += [
                    read(
                        BASE.parent.parent
                        / f"paired{seconds}"
                        / "runs"
                        / f"{name}-0-graph_policy.json"
                    )["metrics"]
                ]
            pairs = []
            for rep in (0, 1):
                old = paired / "runs" / f"{name}-{rep}-graph_policy.json"
                if old.exists():
                    pairs.append(
                        [
                            read(old)["metrics"],
                            read(paired / "runs" / f"{name}-{rep}-graph_refined.json")["metrics"],
                        ]
                    )
            combined = archive + [r for pair in pairs for r in pair]
            conclusions = {(r["status"], r["rho"]) for r in combined if r["status"] in PROVED}
            if len(conclusions) > 1:
                raise ValueError((name, conclusions))
            finite = [r["rho"] for r in combined if r["status"] == "FINITE"]
            bounds = [r["upper"] for r in combined if r["upper"] is not None]
            lower = [r["lower"] for r in combined if r["lower"] is not None]
            assert not lower or ("INFEASIBLE_AT_ZERO", None) not in conclusions
            assert not bounds or ("UNBOUNDED", None) not in conclusions
            assert not lower or not bounds or max(lower) <= min(bounds)
            assert not finite or not lower or max(lower) <= min(finite)
            a, b = pairs[0]
            effects = [flags(*pair) for pair in pairs]
            optimum_lost = [
                a["makespan_optimal"] and not b["makespan_optimal"]
                for a, b in pairs
                if a["status"] == b["status"] == "FINITE"
            ]
            incumbent_loss = [
                (b["makespan"] - a["makespan"])
                for a, b in pairs
                if a["status"] == b["status"] == "FINITE"
            ]
            comparisons.append(
                dict(
                    budget=budget,
                    case=name,
                    old=a["status"],
                    new=b["status"],
                    first_effect=effects[0],
                    reverse_effect=effects[1]
                    if len(effects) > 1
                    else secondary.get(name, {}).get("retest_effect"),
                    unknown_interval=quality(a, b)
                    if a["status"] == b["status"] == "UNKNOWN"
                    else "",
                    old_makespan=a["makespan"],
                    new_makespan=b["makespan"],
                    optimum_lost_any=any(optimum_lost),
                    makespan_worse_any=any(x > 0 for x in incumbent_loss),
                    old_time=a["wall_seconds"],
                    new_time=b["wall_seconds"],
                )
            )
            if budget == 30 and name in certificates:
                r = read(paired / "runs" / f"{name}-0-graph_refined.json")
                detail.append(
                    dict(
                        case=name,
                        archive_lower=old_history["lower"],
                        archive_upper=old_history["upper"],
                        baseline=a["status"],
                        baseline_lower=a["lower"],
                        baseline_upper=a["upper"],
                        status=b["status"],
                        lower=b["lower"],
                        upper=b["upper"],
                        seconds=b["wall_seconds"],
                        evidence=certificates[name],
                        trace=r["trace"],
                    )
                )
    save(folder / "ten-cases.json", detail)
    write_csv(folder / "paired-effects.csv", comparisons)
    profiles = read(folder / "profiles.json")
    groups = sorted({(r["case"], r["budget"], r["method"]) for r in profiles})
    profile_rows = []
    for name, budget, method in groups:
        runs = [
            r for r in profiles if (r["case"], r["budget"], r["method"]) == (name, budget, method)
        ]
        profile_rows.append(
            dict(
                case=name,
                budget=budget,
                method=method,
                repeats=len(runs),
                median_wall=median(r["metrics"]["wall_seconds"] for r in runs),
                **{
                    phase: median(r["phases"].get(phase, 0) for r in runs)
                    for phase in ("snapshot", "build", "cp_sat", "replay", "other")
                },
                calls=sorted({r["counts"]["cp_sat"] for r in runs}),
                branch_signatures=sorted({tuple(c["branches"] for c in r["calls"]) for r in runs}),
            )
        )
    write_csv(folder / "profile-summary.csv", profile_rows)
    import hashlib
    import platform
    from importlib.metadata import version

    source = Path(__file__).parent
    names = (
        "terminal_exact.py",
        "study_policy.py",
        "healthy_witness.py",
        "evidence_study.py",
        "policy_retest.py",
        "terminal_diagnostics.py",
    )
    save(
        folder / "provenance.json",
        dict(
            control_revision="40c019865060283685dc3e1b014a5edea4b806b1",
            python=platform.python_version(),
            platform=platform.system(),
            ortools=version("ortools"),
            langgraph=version("langgraph"),
            source_sha256={
                name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names
            },
            manifest_sha256=hashlib.sha256((ROOT / "manifest.json").read_bytes()).hexdigest(),
            clock="perf_counter wall time including reconstruction and all replays",
            solver_workers=1,
            optimizer_seed=0,
            diagnostic_seed=1,
        ),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["profile", "relax", "zero", "summarize"])
    ap.add_argument("--core", type=int, default=2)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--seconds", type=float, default=3)
    args = ap.parse_args()
    pin(args.core)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "manifest.json").read_bytes())
    if args.action == "summarize":
        summarize(args.out)
    elif args.action == "zero":
        rows = {
            item["case"]: check_zero(read_case(item), args.seconds)
            for item in manifest
            if item["case"] in {"terminal-08-10", "terminal-12-04", "terminal-12-10"}
        }
        save(args.out / "zero-no-cuts.json", rows)
    elif args.action == "profile":
        rows = []
        for item in manifest:
            if item["case"] not in ("kim-01", "terminal-04-02"):
                continue
            case = read_case(item)
            for budget in (1, 30):
                # Balance order and the first/cold position over three permutations twice.
                for rep in range(6):
                    order = METHODS[rep % 3 :] + METHODS[: rep % 3]
                    if rep >= 3:
                        order = tuple(reversed(order))
                    for pos, method in enumerate(order):
                        rows.append(
                            dict(
                                case=item["case"],
                                budget=budget,
                                repeat=rep,
                                position=pos,
                                core=args.core,
                                **profile(case, method, budget),
                            )
                        )
        save(args.out / "profiles.json", rows)
    else:
        rows, math = [], {}
        for item in manifest:
            name = item["case"]
            record = json.loads((BASE / f"{name}-0-graph_policy.json").read_bytes())
            if record["metrics"]["status"] == "UNKNOWN":
                math[name] = relax(read_case(item), rows, name, args.seconds)
        save(args.out / "certificates.json", math)
        write_csv(args.out / "relaxations.csv", rows)


if __name__ == "__main__":
    main()
