"""Compare the two frozen outcome forecasts on exactly the same executed queries in cohort B."""
import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean

from wafer_sched.recovery.feedback.learned_study import read
from wafer_sched.recovery.feedback.learned_query import probability
from wafer_sched.recovery.evidence_study import save


def review(root, earlier):
    logit=read(earlier/"value-model.json")
    rows=[]
    per_case=defaultdict(list)
    for e in read(root/"decisions.json"):
        g=e["chosen"]
        if e["repeat"] or g=="fallback":
            continue
        statuses=[st for tick,st in e["receipts"] if tick==e["tick"]]
        if not statuses:
            continue
        witness=bool(set(statuses)&{"WITNESS","OPTIMAL","FEASIBLE"})
        exclusion="INFEASIBLE" in statuses
        assert not (witness and exclusion)
        truth=(witness,exclusion,not (witness or exclusion))
        success=probability(logit["decisive"][g],e["features"])
        pos=success*probability(logit["witness_given_decisive"][g],e["features"])
        forecasts={"regularized":[pos,success-pos,1-success],
                   "neighbors":[e["forecasts"][g][k] for k in ("witness","exclusion","unresolved")]}
        scores={k:sum((x-y)**2 for x,y in zip(p,truth)) for k,p in forecasts.items()}
        rows.append(dict(case=e["case"],budget=e["budget"],tick=e["tick"],chosen=g,
                         truth=truth,scores=scores))
        per_case[e["case"]].append(scores)
    keys=("regularized","neighbors")
    save(root/"forecast-check.json",dict(queries=len(rows),cases=len(per_case),
        query_mean_brier={k:mean(r["scores"][k] for r in rows) for k in keys},
        case_mean_brier={k:mean(mean(r[k] for r in group) for group in per_case.values()) for k in keys},
        scope="First pass only. Same executed B queries for both forecasters. Tool-receipt prediction only.",
        rows=rows))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("earlier",type=Path)
    args=parser.parse_args()
    review(args.root,args.earlier)
