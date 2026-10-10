"""Small legal-action demonstration driver, not an optimization baseline."""

from .simulator import Simulator


def run_validation_driver(simulator: Simulator, *, max_decisions: int = 10000,
                          max_time: float = 100000.0) -> dict:
    if max_decisions <= 0 or max_time < 0:
        raise ValueError("Driver budgets must be positive decisions and nonnegative time")
    for _ in range(max_decisions):
        if simulator.completed:
            return {"status": "completed", "reason": None}
        if simulator.state.time >= max_time:
            return {"status": "truncated", "reason": "time_budget"}
        actions = [action for action in simulator.legal_actions() if action.kind != "wait"]
        if actions:
            # Finish output transfers, then advance processed wafers, then load input.
            action = min(actions, key=lambda item: (
                item.destination != "OUT",
                simulator.state.wafers[item.wafer_id].location == "LOAD" if item.wafer_id else False,
                item.wafer_id or "", item.destination or "",
            ))
            result = simulator.submit(action)
            if not result:
                raise RuntimeError(f"Driver selected an invalid action: {result.reason}")
        elif simulator.state.events:
            if simulator.state.events[0].time > max_time:
                simulator.run_until(max_time)
                return {"status": "truncated", "reason": "time_budget"}
            simulator.advance_next()
        else:
            return {"status": "deadlocked", "reason": simulator.detect_deadlock()}
    return {"status": "truncated", "reason": "decision_budget"}
