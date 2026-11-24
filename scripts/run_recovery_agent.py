"""Solve one frozen snapshot offline and show which actions actually had alternatives."""
import argparse
import json
from pathlib import Path

from wafer_sched.recovery.feedback.learned_study import run_one
from wafer_sched.recovery.evidence_study import save
from review_value_agent import decisions


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case",help="Case name in the selected corpus, e.g. 16-h-1")
    parser.add_argument("--root",type=Path,default=Path("results/recovery/feedback-study/value-agent-002"))
    parser.add_argument("--budget",type=float,default=30,choices=(1,30))
    parser.add_argument("--out",type=Path,required=True,help="New directory for the run")
    args=parser.parse_args()
    if Path(args.case).name!=args.case or not (args.root/"inputs"/(args.case+".json")).is_file():
        parser.error("Choose an existing snapshot basename")
    args.out.mkdir(parents=True,exist_ok=False)
    result=run_one(args.root,args.case,"value",args.budget)
    result["rep"]=0
    save(args.out/"value.json",result)
    print(json.dumps({k:result[k] for k in ("case","budget","status","lower","upper","wall")}))
    for step in decisions(result):
        print(json.dumps({k:step[k] for k in ("objective","chosen","tick","candidates","actionable_probability","scores","receipts")
                          if k in step}))
