"""One-factor search controls on the two archived incidents; run from repository root."""

import argparse
import json
from pathlib import Path
from ortools.sat.python import cp_model
from .continuation import Continuation
from .direct import direct
from .dispatch import recover
from .evidence_study import ROOT, save
from .model import build_recovery_model, dimensions

OUT = Path("results/recovery/hard-case-policy")


def load_case(name):
    return Continuation.from_dict(
        json.loads((ROOT / "inputs" / f"{name}.json").read_text(encoding="utf8"))
    )


def hint_control(out):
    case = load_case("terminal-08-03")
    early = recover(case, "solve", repair=0, per_query=7.14, total=7.14)
    if not early.get("verification_valid"):
        raise RuntimeError("No verified zero-delay incumbent obtained")
    records = {}
    for mode in ("cold", "warm"):
        result = direct(case, 17.112407, incumbent=early if mode == "warm" else None)
        records[mode] = {
            k: result.get(k)
            for k in ("status", "verified_feasible_lower_seconds", "trace", "incumbent_hint")
        }
    save(
        out / "diagnosis" / "hint-control.json",
        dict(
            equal_wall_allocation=17.112407,
            zero_status=early["status"],
            zero_plan=early["best"]["schedule"],
            controls=records,
        ),
    )


def order_controls(out):
    from .healthy_witness import find_healthy_schedule
    from time import perf_counter
    import copy

    case = load_case("terminal-12-03")
    p, _ = case.prepare()
    witness, _ = find_healthy_schedule(p, perf_counter() + 10)
    if not witness:
        raise RuntimeError("Missing healthy witness for diagnostic controls")
    probe = dimensions(p)[2] + 1
    records = {}
    for mode in (
        "original",
        "no_final_residency",
        "fixed_routes",
        "fixed_robot_order",
        "both_fixed",
    ):
        instance = copy.copy(p)
        if mode == "no_final_residency":
            instance.residency = {k: [*v[:-1], None] for k, v in p.residency.items()}
        bundle = build_recovery_model(instance, probe, minimize_makespan=False)
        by_key = {(t["wafer_id"], t["stage"]): t for t in bundle.tasks}
        ordered = [by_key[t["wafer_id"], t["stage"]] for t in witness["transfers"]]
        if mode in ("fixed_routes", "both_fixed"):
            for task, row in zip(ordered, witness["transfers"]):
                bundle.model.add(task["destination"] == bundle.locations.index(row["destination"]))
        if mode in ("fixed_robot_order", "both_fixed"):
            for a, b in zip(ordered, ordered[1:]):
                bundle.model.add(a["place_end"] <= b["pick_start"])
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.solve(bundle.model)
        records[mode] = dict(
            status=solver.status_name(status),
            branches=solver.num_branches,
            conflicts=solver.num_conflicts,
            solver_seconds=solver.wall_time,
            model_variables=len(bundle.model.proto.variables),
            model_constraints=len(bundle.model.proto.constraints),
        )
    save(
        out / "diagnosis" / "constraint-controls.json",
        dict(
            case="terminal-12-03",
            repair_tick=probe,
            solver_budget=5,
            notes="fixed choices come from an already verified healthy witness; diagnostic only",
            controls=records,
        ),
    )


def witness_report(out):
    from time import perf_counter
    from .healthy_witness import lift_witness, terminal_jobs, verified_bypass
    from .replay import replay_recovery
    from .dispatch import replay_incident

    records = {}
    for n in (8, 12):
        name = f"terminal-{n:02}-03"
        case = load_case(name)
        p, h = case.prepare()
        archived = {}
        for method in ("direct", "graph_policy"):
            artifact = f"{name}-0-{method}.json"
            data = json.loads((ROOT / "stress30/runs" / artifact).read_text(encoding="utf8"))
            plan = data["schedule"]
            r = data["witness_repair"]
            replay = replay_recovery(p, r - h["offset"], plan)
            assert replay["valid"]
            replay_incident(
                case,
                h,
                dict(witness_repair_delay_seconds=r, makespan_seconds=data["raw_makespan"]),
                {"verification": replay},
            )
            lifted = lift_witness(
                case, p, h, dict(verification_valid=True, best=dict(schedule=plan))
            )
            archived[method] = dict(
                source=artifact,
                original_status=data["metrics"]["raw_status"],
                original_witness_delay=r,
                original_makespan=data["raw_makespan"],
                original_trace=data["trace"],
                failed_loads=[
                    t["wafer_id"] for t in plan["transfers"] if t["destination"] == p.failed_chamber
                ],
                lift=lifted[1] if lifted else None,
            )
            if lifted and method == "graph_policy":
                save(
                    out / "diagnosis" / "archived-witness-lift.json",
                    dict(
                        source=artifact,
                        evidence=lifted[1],
                        schedule=lifted[0]["best"]["schedule"],
                        makespan=lifted[0]["makespan_seconds"],
                    ),
                )
        healthy, trace = verified_bypass(case, p, h, perf_counter() + 15)
        assert healthy is not None
        sched = healthy["best"]["schedule"]
        transfers = sched["transfers"]
        rows = []
        for job in terminal_jobs(p):
            load, unload = [t for t in transfers if t["wafer_id"] == job.wafer]
            proc = next(row for row in sched["processes"] if row["wafer_id"] == job.wafer)
            rows.append(
                dict(
                    wafer=job.wafer,
                    healthy_candidates=[c for c, _ in job.choices],
                    used=load["destination"],
                    source_ready=job.ready / p.scale,
                    source_due=job.due / p.scale,
                    source_slack=(job.due - load["pick_end"]) / p.scale,
                    final_residency=job.residence / p.scale,
                    final_slack=(proc["end"] + job.residence - unload["pick_end"]) / p.scale,
                )
            )
        records[name] = dict(
            archived=archived,
            healthy_proof=trace,
            healthy_makespan=healthy["makespan_seconds"],
            transfers=len(transfers),
            wafer_windows=rows,
            schedule=sched,
        )
    save(out / "diagnosis" / "witness-analysis.json", records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["hint", "constraints", "witness"])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    {"hint": hint_control, "constraints": order_controls, "witness": witness_report}[args.mode](
        args.out
    )
