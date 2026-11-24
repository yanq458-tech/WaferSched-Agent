"""Select the query with highest expected gain in the quality of mathematical evidence."""
from time import perf_counter

from .learned_query import FEATURES, GOALS, features, fit, probability


def train(observations):
    decisive = []
    for row in observations:
        receipts = set(row["receipts"])
        witness = bool(receipts & {"WITNESS", "FEASIBLE", "OPTIMAL"})
        exclusion = "INFEASIBLE" in receipts
        if witness and exclusion:
            raise ValueError("Contradictory receipts for one query")
        if bool(row["outcome"]) != (witness or exclusion):
            raise ValueError("Archive label conflicts with its receipts")
        if witness or exclusion:
            decisive.append({**row, "outcome": int(witness)})
    return dict(features=FEATURES, decisive=fit(observations), witness_given_decisive=fit(decisive),
                samples={g:dict(queries=sum(r["goal"]==g for r in observations),
                                witness=sum(r["goal"]==g and r["outcome"] for r in decisive),
                                exclusion=sum(r["goal"]==g and not r["outcome"] for r in decisive))
                         for g in GOALS})


def gains(lo, hi, q):
    """Two explicit unit bonuses: first witness and closed proof; width gain ranges from 0 to 1."""
    if not max(0, lo+1) <= q <= hi:
        raise ValueError("Repair query outside open domain")
    base = max(0, lo)
    span = max(1, hi - base)
    # Conservatively value a witness at the queried tick, even if replay can lift it.
    witness = int(lo < 0) + int(q == hi) + (q - base) / span
    exclusion = int(q == base + (lo >= 0)) + min(1, (hi-q+1) / span)
    return witness, exclusion


def selector(model):
    def select(domain, failed, lo, hi, scale, short, asked, trace, default):
        start = perf_counter()
        x = features(domain, failed, lo, hi, scale, short, trace)
        endpoints = dict(zip(GOALS, (max(0, lo+1), hi)))
        choices = {g:q for g,q in endpoints.items() if q not in asked}
        scores, forecasts = {}, {}
        for g,q in choices.items():
            success = probability(model["decisive"][g], x)
            feasible = success * probability(model["witness_given_decisive"][g], x)
            excluded = success - feasible
            wf, ex = gains(lo, hi, q)
            scores[g] = feasible * wf + excluded * ex
            forecasts[g] = dict(witness=feasible, exclusion=excluded, unresolved=1-success,
                                witness_value=wf, exclusion_value=ex)
        chosen = max(choices, key=lambda g:(scores[g],choices[g] == default)) if choices else "fallback"
        tick = choices.get(chosen, default)
        return tick, dict(tool="value_query", chosen=chosen, tick=tick, default_tick=default,
                          lower_tick=lo, upper_tick=hi, candidates=choices, forecasts=forecasts,
                          scores=scores, features=x, seconds=perf_counter()-start)
    return select
