"""Reachable synthetic incidents and a literature-derived route family."""

import json
import random
from pathlib import Path

from ..actions import Action
from ..config import EquipmentConfig
from ..simulator import Simulator
from .continuation import Continuation


def terminal_case(n, seed):
    rng = random.Random(1000 * n + seed)
    chambers, wafers, residency = [], [], {}
    targets = ["F"] + [f"H{i}" for i in range(1, 1 + n // 2)]
    # Loading the first wafer takes 1.875 s, each subsequent one 2.25 s
    # including the empty return. Choose an exactly reachable common snapshot.
    now = 1.875 + (n - 1) * 2.25 + 1.5
    for i in range(n):
        source, wafer, recipe = f"S{i}", f"W{i}", f"finish{i}"
        ready = now + rng.choice([-0.75, -0.25, 0, 0.5, 1.25])
        chambers.append({"id": source, "processing_times": {"prep": ready - (1.875 + i * 2.25)}})
        options = rng.sample(targets, min(2 + seed % 2, len(targets)))
        if i == 0 and seed % 2 == 0:
            options = ["F"]
        wafers.append(
            {
                "id": wafer,
                "route": [
                    {"recipe": "prep", "chambers": [source]},
                    {"recipe": recipe, "chambers": options},
                ],
            }
        )
        base = [1.75, n * 2, n * 4, n * 6, n * 3, n * 8][seed % 6]
        residency[wafer] = [base + rng.randrange(8) / 8, 0.875 + rng.randrange(24) / 8]
    for dest in targets:
        chambers.append(
            {
                "id": dest,
                "processing_times": {f"finish{i}": 2.125 + rng.randrange(64) / 8 for i in range(n)},
            }
        )
    config = EquipmentConfig.from_dict(
        {
            "name": f"synthetic-terminal-{n}-{seed}",
            "robot": {"pick_seconds": 0.625, "place_seconds": 0.875, "move_seconds": 0.375},
            "chambers": chambers,
            "wafers": wafers,
        }
    )
    sim = Simulator(config)
    for i in range(n):
        assert sim.submit(Action.transfer(f"W{i}", f"S{i}"))
        while sim.state.robot.busy:
            sim.advance_next()
    sim.run_until(now)
    hold = {w["id"]: [None, (20.375 + seed if seed % 2 == 0 else None), None] for w in wafers}
    case = Continuation.capture(sim, "F", residency, hold)
    case.prepare()
    return case


SOURCE = (
    "https://github.com/yeoneee/ClusterToolSchedulingRL/blob/"
    "6a03fb457e86a1bb7423bad47b8868df23d7471d/single_arm_cluster_tool/concurrent_flow/notebook.ipynb"
)


def concurrent_case(seed):
    rng = random.Random(22000 + seed)
    n = 2 + seed % 3
    wafers, chambers, res, holding = [], [], {}, {}
    for i in range(6):
        chambers.append(dict(id=f"PM{i + 1}", processing_times={f"step{i}": rng.randint(10, 300)}))
    for i in range(n):
        route = range(3 * (i % 2), 3 * (i % 2) + 3)
        wafers.append(
            dict(
                id=f"W{i}", route=[dict(recipe=f"step{k}", chambers=[f"PM{k + 1}"]) for k in route]
            )
        )
        res[f"W{i}"] = [700, 350 + rng.randrange(50), 20 + rng.randrange(80)]
        holding[f"W{i}"] = [None] + [rng.choice([4.75, 16.25, 60.5]) for _ in range(3)]
    config = EquipmentConfig.from_dict(
        dict(
            name=f"kim-concurrent-derived-{seed}",
            robot=dict(pick_seconds=0.625, place_seconds=0.875, move_seconds=0.375),
            chambers=chambers,
            wafers=wafers,
        )
    )
    sim = Simulator(config)

    def transfer(i, c):
        assert sim.submit(Action.transfer(f"W{i}", f"PM{c}"))
        while sim.state.robot.busy:
            sim.advance_next()

    for i in range(2):
        transfer(i, 1 + 3 * i)
    for i in range(n - 2):
        first = 1 + 3 * i
        ready = sim.state.chambers[f"PM{first}"].ready_at
        if ready is not None:
            sim.run_until(max(ready, sim.state.time))
        transfer(i, first + 1)
        transfer(i + 2, first)
    # The paper supplies routes and the processing-time range only.
    # This fault, the history, robot times and quality windows are synthetic.
    return Continuation.capture(sim, "PM3" if seed % 2 else "PM6", res, holding)


def corpus(seed_file):
    seed_case = json.loads(Path(seed_file).read_text(encoding="utf8"))
    for n in (2, 4, 6, 8, 12):
        for seed in range(12):
            yield (
                f"terminal-{n:02}-{seed:02}",
                "synthetic_competition",
                seed,
                terminal_case(n, seed),
            )
    for seed in range(48):
        yield f"kim-{seed:02}", "kim_concurrent_derived", seed, concurrent_case(seed)
    for seed in range(12):
        case = Continuation.from_dict(seed_case)
        case.residency["W1"][0] += seed / 8
        case.residency["W2"][1] += (seed % 4) / 8
        yield f"chain-{seed:02}", "synthetic_mid_pick", seed, case
