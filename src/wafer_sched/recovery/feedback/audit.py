"""Check development witnesses and rerun boundary certificates separately from benchmark timings."""

import argparse
import gzip
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from time import perf_counter
from unittest.mock import patch
from ortools.sat.python import cp_model
from ..holdout import OUT, CORES
from ..continuation import Continuation
from ..dispatch import replay_incident
from ..conflict_evidence import verify_bound
from ..evidence_study import save
from ..policy_retest import pin, write_csv
from ..replay import replay_recovery
from ..short_budget import PreparedIncident
from ..terminal_exact import terminal_domain
from .capacity import bound
from .diagnosis import ROOT
from .exact import fixed_query


def replay(case, plan, delay):
    p, prefix = case.prepare()
    v = replay_recovery(p, delay - prefix["offset"], plan)
    assert v["valid"], v["errors"]
    replay_incident(
        case,
        prefix,
        dict(
            witness_repair_delay_seconds=delay,
            makespan_seconds=prefix["offset"] + plan["makespan_tick"] / p.scale,
        ),
        {"verification": v},
    )


def probe_archive(name, tag, p, domain, q, seconds):
    folder = ROOT / "rechecks"
    folder.mkdir(exist_ok=True)
    model_path = folder / f"{name}-{tag}.pb.gz"
    original = cp_model.CpSolver.solve

    def capture(s, model, *a, **kw):
        blob = model.proto.SerializeToString()
        model_path.write_bytes(gzip.compress(blob, mtime=0))
        return original(s, model, *a, **kw)

    with patch.object(cp_model.CpSolver, "solve", capture):
        status, plan, _, details = fixed_query(p, domain, q, perf_counter() + seconds)
    note = dict(
        status=status,
        repair_tick=q,
        budget=seconds,
        model=model_path.name,
        model_sha256=hashlib.sha256(gzip.decompress(model_path.read_bytes())).hexdigest(),
        details=details,
    )
    return note, plan


def lateness_probe(case, p, prefix, domain, name, seconds):
    """Zero repair with an explicit deviation from the original source deadlines."""
    from dataclasses import replace
    from math import floor
    from ..terminal_exact import build
    from ..solver import read_witness

    jobs, *timing = domain
    # Every original feasible schedule maps to delay=0, regardless of this upper bound.
    tolerance = max(j.due for j in jobs)
    relaxed = [replace(j, due=j.due + tolerance) for j in jobs]
    bundle = build(p, (relaxed, *timing), 0)
    excess = bundle.model.new_int_var(0, tolerance, "max_source_lateness")
    for j, task in zip(jobs, bundle.tasks[::2], strict=True):
        bundle.model.add(task["pick_end"] <= j.due + excess)
    bundle.model.minimize(excess)
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    s.parameters.random_seed = 0
    s.parameters.max_time_in_seconds = seconds
    st = s.solve(bundle.model)
    if st == cp_model.MODEL_INVALID:
        raise ValueError(bundle.model.validate())
    feasible = st in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    lb = floor(s.best_objective_bound) if feasible else None
    ub = s.value(excess) if feasible else None
    verdict = (
        "INFEASIBLE" if st == cp_model.INFEASIBLE or (lb is not None and lb > 0) else "UNKNOWN"
    )
    plan = None
    if ub == 0:
        plan, check = read_witness(p, bundle, s, 0)
        assert check["valid"]
        replay(case, plan, prefix["offset"])
        verdict = "FEASIBLE"
    data = bundle.model.proto.SerializeToString()
    path = ROOT / "rechecks" / f"{name}-lateness.pb.gz"
    path.write_bytes(gzip.compress(data, mtime=0))
    save(
        path.with_suffix("").with_suffix(".json"),
        dict(
            status=s.status_name(st),
            seconds=s.wall_time,
            solver_budget=seconds,
            lower_lateness_ticks=lb,
            upper_lateness_ticks=ub,
            original_verdict=verdict,
            model_sha256=hashlib.sha256(data).hexdigest(),
            schedule=plan,
        ),
    )
    return verdict


def check(job):
    file, core, extra = job
    pin(core)
    data = json.loads(file.read_bytes())
    name = data["case"]
    old = data["old"]
    case = Continuation.from_dict(json.loads((OUT / "inputs" / (name + ".json")).read_bytes()))
    p, prefix = PreparedIncident(**vars(case)).prepare()
    domain = terminal_domain(p)
    result = data["result"]
    up = result["finite_upper_seconds"]
    lo = result.get("verified_feasible_lower_seconds")
    assert data["credited"] == (data["wall_seconds"] <= 30)
    if data["schedule"]:
        replay(case, data["schedule"], result["witness_repair_delay_seconds"])
    cert = result["certificate"]
    assert verify_bound(p, cert)
    upper = cert["upper_tick"]
    limit = round((up - prefix["offset"]) * p.scale) if up is not None else -1
    verification = "route certificate"
    if upper > limit:
        relaxed, note = bound(p, domain, upper, perf_counter() + 15)
        assert lo is None or prefix["offset"] + relaxed / p.scale >= lo
        if relaxed <= limit:
            verification = "relaxed optimization"
            save(ROOT / "rechecks" / f"{name}-relaxation.json", note)
        else:
            note, _ = probe_archive(name, "next", p, domain, limit + 1, 45)
            verification = "next tick " + note["status"]
            save(ROOT / "rechecks" / f"{name}-next.json", note)
    extra_status = None
    diagnostic_status = None
    if extra and lo is None and limit >= 0:
        note, plan = probe_archive(name, "zero", p, domain, 0, 60)
        extra_status = note["status"]
        if plan:
            replay(case, plan, prefix["offset"])
        save(
            ROOT / "rechecks" / f"{name}-zero.json",
            dict(**note, schedule=plan, replayed=bool(plan)),
        )
        if extra_status == "UNKNOWN":
            diagnostic_status = lateness_probe(case, p, prefix, domain, name, 30)
    return dict(
        case=name,
        archived_lower=old["lower"],
        archived_upper=old["upper"],
        status=result["status"],
        lower=lo,
        upper=up,
        seconds=data["wall_seconds"],
        on_time=data["credited"],
        upper_check=verification,
        witness_replayed=bool(data["schedule"]),
        separate_zero_60s=extra_status,
        separate_lateness_30s=diagnostic_status,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra-zero", action="store_true")
    a = ap.parse_args()
    files = sorted((ROOT / "accepted-development").glob("*.json"))
    assert len(files) == 10
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(check, [(f, CORES[i % 4], a.extra_zero) for i, f in enumerate(files)]))
    write_csv(ROOT / "development.csv", rows)
