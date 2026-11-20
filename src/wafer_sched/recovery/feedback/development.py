"""Diagnostic runs on the ten past misses. Historical witnesses are development inputs only."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from time import perf_counter
from ..holdout import OUT, CORES
from ..continuation import Continuation
from ..short_budget import PreparedIncident
from ..evidence_study import save
from ..policy_retest import pin
from ..terminal_exact import terminal_domain
from .diagnosis import ROOT
from .exact import fixed_query


def lane(items, core, mode):
    pin(core)
    for name in items:
        src = json.loads((OUT / "inputs" / (name + ".json")).read_bytes())
        old = json.loads((OUT / "b30" / name / "0-agent.json").read_bytes())
        case = Continuation.from_dict(src)
        if mode == "zero":
            p, _ = PreparedIncident(**vars(case)).prepare()
            st, s, check, log = fixed_query(p, terminal_domain(p), 0, perf_counter() + 8)
            save(
                ROOT / "zero-probes" / (name + ".json"),
                dict(status=st, schedule=s, replayed=bool(check and check["valid"]), log=log),
            )
        else:
            from .policy import solve

            start = perf_counter()
            result = solve(
                case,
                25.5,
                "agent",
                incumbent=old["evidence"] if old["metrics"]["verified"] else None,
            )
            elapsed = perf_counter() - start
            save(
                ROOT / "accepted-development" / (name + ".json"),
                dict(
                    case=name,
                    wall_seconds=elapsed,
                    credited=elapsed <= 30,
                    old=old["metrics"],
                    result={k: v for k, v in result.items() if k != "best"},
                    schedule=(result.get("best") or {}).get("schedule"),
                ),
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["zero", "study"])
    mode = parser.parse_args().mode
    items = []
    for path in sorted((OUT / "b30").glob("*/0-agent.json")):
        m = json.loads(path.read_bytes())["metrics"]
        if m["status"] == "UNKNOWN" and (mode == "study" or not m["verified"]):
            items.append(path.parent.name)
    with ProcessPoolExecutor(max_workers=4) as pool:
        fs = [pool.submit(lane, items[i::4], c, mode) for i, c in enumerate(CORES)]
        for f in fs:
            f.result()
