"""Targeted development check on the previously known witness loss; excluded from blind counts."""
import argparse
from pathlib import Path
import shutil

from wafer_sched.recovery.evidence_study import save
from wafer_sched.recovery.feedback.learned_study import PREVIOUS, read, run_one
from wafer_sched.recovery.feedback.audit import replay
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.policy_retest import pin


def main(root):
    case_name = "16-h-3"
    target = root/"previous-witness-check"
    target.mkdir(exist_ok=False)
    (target/"inputs").mkdir()
    src = PREVIOUS/"inputs"/(case_name+".json")
    shutil.copyfile(src,target/"inputs"/src.name)
    shutil.copyfile(root/"value-model.json",target/"value-model.json")
    pin(2)
    # Only the archived input is passed to the new solver. Historical plans are not inputs.
    record = run_one(target,case_name,"value",30)
    save(target/"value.json",record)
    if record["lower"] is not None:
        replay(Continuation.from_dict(read(src)),record["raw"]["best"]["schedule"],record["lower"])
    save(target/"comparison.json",{
        "historical":[{k:read(PREVIOUS/"runs"/"30"/case_name/f"0-{arm}.json")[k]
                      for k in ("arm","status","lower","upper","wall")} for arm in ("human","learned")],
        "new_check":{k:record[k] for k in ("arm","status","lower","upper","wall")},
        "purpose":"known development incident; single cold solve with extra retrospective replay"
    })


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    main(parser.parse_args().root)
