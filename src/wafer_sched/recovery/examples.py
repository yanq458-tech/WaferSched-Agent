"""Small reproducible warm states produced by the existing Simulator itself."""

from ..actions import Action
from ..config import EquipmentConfig
from ..simulator import Simulator
from .state import RecoveryProblem


def terminal_competition(*, m=2, count=None, deadline=6, processing=10, residency=1,
                         deadlines=None, process_times=None, residencies=None):
    count = count if count is not None else m + 1
    if m < 0 or count < 1:
        raise ValueError("Invalid example size")
    ds = deadlines if deadlines is not None else [deadline] * count
    ps = process_times if process_times is not None else [processing] * count
    rs = residencies if residencies is not None else [residency] * count
    if any(len(v) != count for v in (ds, ps, rs)):
        raise ValueError("Example vectors must match count")
    targets = [*(f"H{i+1}" for i in range(m)), "F"]
    config = EquipmentConfig.from_dict({
        "name": "recovery-terminal-competition",
        "robot": {"pick_seconds": 1, "place_seconds": 1, "move_seconds": 0},
        "chambers": [
            *[{"id": f"S{i+1}", "processing_times": {f"prep{i}": 2*(count-i-1)+1}}
              for i in range(count)],
            *[{"id": key, "processing_times": {f"finish{i}": ps[i] for i in range(count)}}
              for key in targets]],
        "wafers": [{"id": f"W{i+1}", "route": [
            {"recipe": f"prep{i}", "chambers": [f"S{i+1}"]},
            {"recipe": f"finish{i}", "chambers": targets}]} for i in range(count)]})
    sim = Simulator(config)
    for i in range(count):
        assert sim.submit(Action.transfer(f"W{i+1}", f"S{i+1}"))
        while sim.state.robot.busy:
            sim.advance_next()
    sim.run_until(2*count+1)
    return RecoveryProblem(config, sim.snapshot(), "F",
                           {f"W{i+1}": [ds[i], rs[i]] for i in range(count)})
