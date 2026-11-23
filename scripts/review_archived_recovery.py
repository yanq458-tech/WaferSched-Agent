"""Check a published recovery certificate. --live makes one optional DeepSeek tool-selection call."""
import argparse
import json
from pathlib import Path
from typing import Literal

from wafer_sched.langgraph_agent.llm import LLMClient, LLMSettings
from wafer_sched.langgraph_agent.schemas import ClosedModel, Limits
from wafer_sched.recovery.conflict_evidence import verify_bound
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.feedback.exclusive_check import verify
from wafer_sched.recovery.replay import replay_recovery

ROOT = Path("results/recovery/feedback-study/final-holdout")
CASES = {"boundary": "blind-16-m-f1", "congestion": "blind-20-h-f1"}


class Selection(ClosedModel):
    tool: Literal["boundary", "congestion"]


def check(tool):
    case = CASES[tool]
    snapshot = json.loads((ROOT / "inputs" / f"{case}.json").read_bytes())
    record = json.loads((ROOT / "b30" / case / "0-agent.json").read_bytes())
    problem, prefix = Continuation.from_dict(snapshot).prepare()
    evidence = record["evidence"]
    if tool == "boundary":
        assert prefix["offset"] == 0
        repair = record["metrics"]["rho"]
        cert = evidence["certificate"]
        valid = (verify_bound(problem, cert) and repair * problem.scale == cert["upper_tick"]
                 and replay_recovery(problem, repair, evidence["schedule"])["valid"])
    else:
        valid = verify(problem, evidence["trace"][0])
    if not valid:
        raise ValueError(f"Archived evidence failed verification for {case}")
    return {"case": case, "guarantee": record["metrics"]["status"], "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.live:
        print(json.dumps([check(t) for t in CASES]))
        return
    if args.out is None:
        parser.error("--live requires a fresh --out directory")
    settings = LLMSettings.from_local(Path(".env"), {"max_output_tokens": 80, "timeout_seconds": 30})
    if not settings.configured or settings.base_url.rstrip("/") not in {
        "https://api.deepseek.com", "https://api.deepseek.com/v1"
    }:
        parser.error("Project-local DeepSeek settings required")
    args.out.mkdir(parents=True, exist_ok=False)
    client = LLMClient(settings, Limits(max_llm_calls=1, max_total_tokens=5000,
                                        max_api_usd=0.002), args.out / "private-call.jsonl")
    prompt = {"task": "Choose one archived evidence check for a final project demonstration. "
              "Prefer the tool that can explain why immediate repair fails.",
              "tools": {"boundary": "Replay a 16-wafer witness and check its repair upper bound.",
                        "congestion": "Verify a 20-wafer shared-chamber deadline certificate."}}
    reply, _ = client.call("closeout_evidence_selection", prompt, Selection, 30)
    tool = Selection.model_validate(reply).tool
    raw = client.records[-1]
    record = {"purpose": "archived evidence verification only", "model": raw["response"]["model"],
              "http_status": raw["http_status"], "decision": tool, "check": check(tool),
              "usage": client.totals()}
    (args.out / "receipt.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
