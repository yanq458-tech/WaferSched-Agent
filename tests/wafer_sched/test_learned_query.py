from types import SimpleNamespace

from wafer_sched.recovery.feedback.learned_query import FEATURES, GOALS, fit, probability, selector


def test_response_fit_uses_predecision_evidence():
    rows = []
    for case in range(8):
        for has_witness in (0, 1):
            x = [0] * len(FEATURES)
            x[4] = has_witness
            for idx, goal in enumerate(GOALS):
                rows.append(dict(case=str(case), goal=goal, x=x, outcome=int(idx == has_witness)))
    model = fit(rows)
    for witness in (0, 1):
        x = [0] * len(FEATURES)
        x[4] = witness
        assert max(GOALS, key=lambda g: probability(model[g], x)) == GOALS[witness]


def test_only_untried_candidates_or_original_fallback():
    model = {"coefficients": {goal: [bias] + [0] * len(FEATURES)
                              for goal, bias in zip(GOALS, (-1, 1))}}
    query = selector(model)
    domain = ([SimpleNamespace(choices=[("F", 8)])], 1, 1, 1)
    for asked, expected in [(set(), 10), ({10}, 0), ({0, 10}, 5)]:
        tick, event = query(domain, "F", -1, 10, 8, True, asked, [], 5)
        assert tick == expected
        assert set(event["scores"]) == set(GOALS)
        assert tick not in asked
