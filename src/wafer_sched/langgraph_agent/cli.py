"""Independent stage-seven CLI with a live preflight gate and explicit resume."""

import argparse
import json

from pydantic import BaseModel, ConfigDict

from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.infrastructure.paths import resolve_path

from .graph import ResearchRuntime
from .llm import LLMSettings, LLMClient, LLMUnavailable
from .reporting import publish_comparison
from .schemas import Limits


class ConnectivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


def preflight(output, study):
    output = resolve_path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = LLMSettings.from_local(
        resolve_path(".env"), {**study.get("llm", {}), "max_output_tokens": 64}
    )
    limits = Limits(
        max_rounds=1,
        total_seconds=30.0,
        max_llm_calls=1,
        max_total_tokens=10000,
        max_api_usd=0.01,
    )
    client = LLMClient(settings, limits, output / "llm_calls.jsonl")
    result = {
        "model": settings.model,
        "configured": settings.configured,
        "success": False,
        "actual_llm_rounds": 0,
        "token_usage_status": "not_reported",
    }
    try:
        raw, _ = client.call(
            "connectivity",
            {"task": 'Connectivity probe: return JSON {"ok":true}.'},
            ConnectivityResponse,
            25,
        )
        result["success"] = ConnectivityResponse.model_validate(raw).ok
    except LLMUnavailable as exc:
        result["failure_code"] = str(exc)
    result.update(client.totals())
    if client.records:
        last = client.records[-1]
        result["http_status"] = last.get("http_status")
        result["provider_error"] = last.get("provider_error")
        result["returned_model_id"] = (last.get("response") or {}).get("model")
        choices = (last.get("response") or {}).get("choices") or []
        result["model_reply"] = (
            choices[0].get("message", {}).get("content") if choices else None
        )
    if result["reported_total_tokens"]:
        result["token_usage_status"] = "provider_reported"
    atomic_record(output / "summary.json", result)
    return result


def live_gate(path, study):
    if not path:
        return False
    probe = json.loads(resolve_path(path).read_text(encoding="utf-8"))
    settings = LLMSettings.from_local(resolve_path(".env"), study.get("llm", {}))
    return bool(
        probe.get("success")
        and probe.get("successful_api_calls", 0) > 0
        and probe.get("model") == settings.model
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="LangGraph stateful wafer mathematics research"
    )
    parser.add_argument("command", choices=["check-llm", "run", "suite"])
    parser.add_argument(
        "--config", default="configs/wafer_sched/langgraph/stage7_study.json"
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--mode", choices=["deterministic", "llm", "fixed"], default="llm"
    )
    parser.add_argument(
        "--preflight", help="Successful real connectivity summary required for B"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pause-after", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    study = json.loads(resolve_path(args.config).read_text(encoding="utf-8"))
    Limits.model_validate(study["limits"])
    root = resolve_path(args.output)
    if args.command == "check-llm":
        result = preflight(root, study)
        print(json.dumps(result, indent=2))
        return 0 if result["success"] else 2
    if args.command == "run":
        if args.mode == "llm" and not live_gate(args.preflight, study):
            parser.error(
                "Real LLM run requires a successful --preflight summary; no paid loop started"
            )
        runtime = ResearchRuntime(
            study, args.mode, root, seed=args.seed, resume=args.resume
        )
        try:
            result = runtime.run(resume=args.resume, pause_after=args.pause_after)
        finally:
            runtime.close()
        print(json.dumps(result, indent=2))
        return 0
    if args.resume or args.pause_after:
        parser.error("Use run for controlled boundary pause/resume")
    root.mkdir(parents=True, exist_ok=False)
    summaries = {}
    for arm, mode in [("A", "deterministic"), ("B", "llm"), ("C", "fixed")]:
        if mode == "llm" and not live_gate(args.preflight, study):
            summary = {
                "status": "blocked",
                "arm": "llm",
                "reason": "real_api_connectivity_not_passed",
                "real_llm_planned_rounds": 0,
                "scenarios": {},
                "no_synthetic_llm_results": True,
            }
            (root / arm).mkdir()
            atomic_record(root / arm / "summary.json", summary)
            summaries[arm] = summary
            continue
        runtime = ResearchRuntime(study, mode, root / arm, seed=args.seed)
        try:
            summaries[arm] = runtime.run()
        finally:
            runtime.close()
    publish_comparison(root, summaries)
    print(
        json.dumps(
            {
                a: {
                    "status": s["status"],
                    "rounds": s.get("rounds", 0),
                    "real_llm_rounds": s.get("real_llm_planned_rounds", 0),
                }
                for a, s in summaries.items()
            },
            indent=2,
        )
    )
    return 0 if summaries["B"].get("real_llm_acceptance_passed") else 3


if __name__ == "__main__":
    raise SystemExit(main())
