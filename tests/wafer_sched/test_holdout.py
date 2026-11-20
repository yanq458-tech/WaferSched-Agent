import pytest
from wafer_sched.recovery.holdout import METHODS, run_method
from wafer_sched.recovery.holdout_review import describe
from wafer_sched.recovery.study_data import terminal_case


@pytest.mark.parametrize("method", METHODS)
def test_all_holdout_arms_report_an_actual_proof_on_old_smoke_input(method):
    # Old development input, independent of the newly frozen evaluation cases.
    incident = terminal_case(4, 0)
    result = run_method(incident, method, 2)
    assert result["status"] == "INFEASIBLE_AT_ZERO"
    if method != "single":
        assert result["certificate"]["kind"] == "terminal_capacity_workload"


def test_unknown_reason_distinguishes_late_verified_work():
    run = dict(
        metrics=dict(status="UNKNOWN", raw_status="FINITE", wall_seconds=1.2, late=True),
        evidence=dict(trace=[], raw_verified=True),
        calls=[],
        phases=dict(replay=0.9, build=0.1),
    )
    explanation = describe(run)
    assert "重放" in explanation and "超时" in explanation and "FINITE" in explanation
    assert "不可行证明" not in explanation
