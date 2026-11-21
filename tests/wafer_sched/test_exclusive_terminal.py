from copy import deepcopy

import pytest

from wafer_sched.actions import Action
from wafer_sched.config import EquipmentConfig
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.feedback.exclusive_check import certificate, verify
from wafer_sched.recovery.primitive_oracle import enumerate_incident
from wafer_sched.simulator import Simulator


@pytest.mark.parametrize("travel", [0, 1])
@pytest.mark.parametrize("slack", [-1, 0, 1])
def test_exclusive_conflict_at_exact_deadline(travel, slack):
    # Start at S1. W1 has the faster cycle and W0 can be picked last at equality.
    n = 2
    loading = 2 + travel
    step = loading + travel
    fault = loading + step + 1
    config = EquipmentConfig.from_dict(dict(
        name="exclusive-independent-check",
        robot=dict(move_seconds=travel, pick_seconds=1, place_seconds=1),
        chambers=[dict(id=f"S{i}", processing_times={"prep": fault - loading - i * step})
                  for i in range(n)] + [dict(id="F", processing_times={"p0": 5, "p1": 2})],
        wafers=[dict(id=f"W{i}", route=[dict(recipe="prep", chambers=[f"S{i}"]),
                                        dict(recipe=f"p{i}", chambers=["F"])]) for i in range(n)]))
    sim = Simulator(config)
    for i in range(n):
        assert sim.submit(Action.transfer(f"W{i}", f"S{i}"))
        while sim.state.robot.busy:
            sim.advance_next()
    sim.run_until(fault)
    due = 4 + 3 * travel + 2 + 1 + slack
    case = Continuation.capture(sim, "F", {f"W{i}": [due, 2] for i in range(n)},
                                {f"W{i}": [None] * 3 for i in range(n)})
    problem, _ = case.prepare()
    certificates = certificate(problem)
    result = enumerate_incident(case, 0, horizon=35)
    assert result["status"] == ("INFEASIBLE" if slack < 0 else "OPTIMAL")
    assert bool(certificates) == (slack < 0)
    if certificates:
        assert verify(problem, certificates[0])
        tampered = deepcopy(certificates[0])
        tampered["last_cases"][0]["earliest_pick"] += 1
        assert not verify(problem, tampered)


def test_alternative_chamber_prevents_exclusive_certificate():
    from wafer_sched.recovery.examples import terminal_competition

    problem = terminal_competition(m=1, count=3, deadline=3)
    assert certificate(problem) == []


def test_compact_replay_preserves_quality_checks_and_physical_events():
    from wafer_sched.recovery.continuation import checks
    from wafer_sched.recovery.feedback.replay_state import FeedbackIncident
    from wafer_sched.recovery.study_data import terminal_case

    incident = terminal_case(3, 2)
    short = FeedbackIncident(**vars(incident))
    original, compact = incident.at_fault(), short.at_fault()
    assert compact.snapshot() == original.snapshot()
    assert checks(compact.trace, incident.residency, incident.holding) == checks(
        original.trace, incident.residency, incident.holding)
    assert len(original.trace) == len(compact.trace)
    for old, new in zip(original.trace, compact.trace):
        assert {k:v for k,v in old.items() if k not in {"state_before", "state_after"}} == {
            k:v for k,v in new.items() if k != "state_before"}
        if new["event"] in {"RobotPickComplete", "RobotPlaceComplete"}:
            wafer = new["wafer_id"]
            assert new["state_before"]["wafers"][wafer] == old["state_before"]["wafers"][wafer]
