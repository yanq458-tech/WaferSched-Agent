"""Solve a schema-2 incident or independently check a supplied bound certificate."""

import argparse
import json
from pathlib import Path

from .conflict_evidence import verify_bound
from .continuation import Continuation
from .direct import direct
from .milp_reference import reference_incident
from .study_policy import adaptive
from .dispatch import recover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("method", choices=["direct", "milp", "check", "binary", "plain", "agent"])
    parser.add_argument("incident", type=Path)
    parser.add_argument("--budget", type=float, default=10)
    parser.add_argument("--repair", type=float, default=0)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--without-cuts", action="store_true")
    args = parser.parse_args()
    case = Continuation.from_dict(json.loads(args.incident.read_text(encoding="utf8")))
    if args.method == "direct":
        result = direct(case, args.budget, cuts=not args.without_cuts)
    elif args.method in ("plain", "agent"):
        result = adaptive(case, args.budget, graph=args.method == "agent")
    elif args.method == "binary":
        result = recover(case, "boundary", total=args.budget, per_query=args.budget)
    elif args.method == "milp":
        result = reference_incident(case, args.repair, seconds=args.budget)
    else:
        if not args.certificate:
            parser.error("check requires --certificate (a direct output or standalone certificate)")
        value = json.loads(args.certificate.read_text(encoding="utf8"))
        cert = value.get("certificate", value)
        p, prefix = case.prepare()
        ok = p is not None and verify_bound(p, cert)
        result = dict(valid=ok)
        if ok:
            result["repair_upper_seconds"] = prefix["offset"] + cert["upper_tick"] / p.scale
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf8")
    else:
        print(payload)
    if args.method == "check" and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
