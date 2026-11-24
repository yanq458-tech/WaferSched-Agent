"""Select queries using logged outcomes at nearby training snapshots plus current verified evidence."""
from time import perf_counter
from ..learned_query import GOALS, features
from ..value_query import gains
from . import estimator


def selector(model):
    predict = estimator(model["table"],model["neighbors"])

    def select(domain, failed, lo, hi, scale, short, asked, trace, default):
        start = perf_counter()
        state = features(domain, failed, lo, hi, scale, short, trace)
        choices = {goal:q for goal,q in zip(GOALS,(max(0,lo+1),hi)) if q not in asked}
        forecasts, scores, disposition = {}, {}, {}
        for goal,q in choices.items():
            witness, exclusion, unresolved = predict(goal,state)
            wf,ex = gains(lo,hi,q)
            scores[goal] = witness*wf + exclusion*ex
            # A witness is usable; infeasibility at zero also disposes of the entire incident.
            disposition[goal] = witness + exclusion * (q == 0)
            forecasts[goal] = dict(witness=witness,exclusion=exclusion,unresolved=unresolved,
                                   witness_value=wf,exclusion_value=ex)
        def priority(goal):
            return (disposition[goal] if lo < 0 else scores[goal], scores[goal], choices[goal]==default)
        goal = max(choices,key=priority) if choices else "fallback"
        q = choices.get(goal,default)
        return q,dict(tool="value_query", chosen=goal,tick=q,default_tick=default,lower_tick=lo,
            upper_tick=hi,candidates=choices,forecasts=forecasts,scores=scores,features=state,
            objective="first_actionable_result" if lo < 0 else "close_verified_interval",
            actionable_probability=disposition,seconds=perf_counter()-start)
    return select
