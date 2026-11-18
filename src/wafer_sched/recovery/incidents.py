"""Deterministic incidents built by executing the original event engine."""

from ..actions import Action
from ..simulator import Simulator
from .continuation import Continuation
from .examples import terminal_competition


def scenarios():
    cases = {}
    for name, n, m, ds in [
        ("two", 2, 1, [4, 4]),
        ("three", 3, 2, [6] * 3),
        ("overload", 3, 2, [3] * 3),
        ("heterogeneous", 2, 1, [5, 6]),
    ]:
        base = terminal_competition(
            count=n,
            m=m,
            deadlines=ds,
            process_times=[6, 8] if name == "heterogeneous" else [10] * n,
            residencies=[1, 2] if name == "heterogeneous" else [1] * n,
        )
        sim = Simulator(base.config)
        for i in range(n):
            sim.submit(Action.transfer(f"W{i + 1}", f"S{i + 1}"))
            while sim.state.robot.busy:
                sim.advance_next()
        sim.run_until(base.now)

        def capture(failed="F", **kw):
            return Continuation.capture(sim, failed, base.residency, **kw)

        cases[name] = capture()
        if name == "two":
            cases["evacuate"] = capture("S2", policy="evacuate_finished")
            cases["sealed"] = capture("S2", policy="sealed_finished")
            cases["unqualified"] = capture("S2")
            cases["dispatch_lag"] = capture(dispatch_lag=1)
            sim.submit(Action.pick("W2", "S2"))
            sim.run_until(base.now + 0.5)
            cases["mid_pick"] = capture()
            sim.advance_next()
            sim.submit(Action.move("F"))
            sim.submit(Action.place("W2", "F"))
            sim.run_until(sim.state.time + 0.5)
            cases["mid_place"] = capture("H1")
            cases["fault_during_load"] = capture()
            sim.advance_next()
            cases["interrupted_process"] = capture()
            cases["healthy_processing"] = capture("H1")
    cfg = base.config.to_dict()
    cfg["wafers"][0]["route"][-1]["chambers"] = ["H1"]
    cfg["robot"]["move_seconds"] = 2
    from ..config import EquipmentConfig

    sim = Simulator(EquipmentConfig.from_dict(cfg))
    for i in range(2):
        assert sim.submit(Action.transfer(f"W{i + 1}", f"S{i + 1}"))
        while sim.state.robot.busy:
            sim.advance_next()
    sim.run_until(sim.state.time + 2)
    assert sim.submit(Action.pick("W2", "S2"))
    sim.advance_next()
    assert sim.submit(Action.move("F"))
    sim.run_until(sim.state.time + 1)
    cases["mid_move"] = Continuation.capture(sim, "F", {"W1": [40, 5], "W2": [40, 5]})
    return cases
