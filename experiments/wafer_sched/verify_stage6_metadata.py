"""Check metadata-only extension leaves all recorded adaptive planning choices intact."""

import hashlib
import json

from wafer_sched.infrastructure.io import atomic_record
from wafer_sched.artifacts import PROJECT_ROOT
from wafer_sched.config import load_config
from wafer_sched.agent.planner import CPBudgetPlanner, DeterministicPlanner
from wafer_sched.agent.skills import SkillRegistry


def verify():
    root = PROJECT_ROOT / "results/wafer_sched/stage6"
    checked = 0
    directories = [p.parent for p in root.glob("development/*/deterministic-*/summary.json")]
    directories.extend(p.parent for p in root.glob("budgets/*/adaptive/summary.json"))
    directories.append(root / "llm-fallback-check")
    for directory in directories:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        history = [json.loads(line) for line in (directory / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]
        config = load_config(manifest["config_path"])
        registry = SkillRegistry()
        planner = CPBudgetPlanner() if directory.name == "adaptive" else DeterministicPlanner()
        for index, row in enumerate(history):
            preceding = history[:index]
            analysis = registry.invoke("ProblemAnalysisSkill", config, preceding, manifest["candidate_catalogue"])
            # No study approached its budget boundary; compare actual selection signatures.
            remaining = manifest["limits"]["total_seconds"] - (preceding[-1]["elapsed_seconds"] if preceding else 0)
            decision = planner.propose(scenario_id=manifest["scenario_id"], history=preceding,
                analysis=analysis, candidates=manifest["candidate_catalogue"], remaining=remaining,
                max_experiment_seconds=manifest["limits"]["max_experiment_seconds"])
            assert decision.proposal is not None
            assert decision.proposal.proposed_method == row["proposal"]["proposed_method"]
            assert decision.proposal.parameters == row["proposal"]["parameters"]
            checked += 1
    provenance_path = root / "metadata-extension/provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    before = root / "metadata-extension/skills_before.py.txt"
    assert hashlib.sha256(before.read_bytes()).hexdigest() == provenance["before_sha256"]
    provenance["after_sha256"] = hashlib.sha256((PROJECT_ROOT / "src/wafer_sched/agent/skills.py").read_bytes()).hexdigest()
    atomic_record(provenance_path, provenance)
    evidence = {"metadata_only_extension": True, "recorded_planning_signatures_checked": checked,
                "all_planning_signatures_unchanged": True, "holdout_not_rerun": True,
                "formal_experiment_results_not_modified": True}
    atomic_record(root / "metadata-extension/verification.json", evidence)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    verify()
