"""Future interface only; no source write or executable code from an LLM."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeImprovementRequest:
    hypothesis: str
    evidence_ids: tuple[str, ...]
    requested_tests: tuple[str, ...]


class CodeImprovementSkill:
    enabled = False

    def propose(self, request: CodeImprovementRequest):
        return {
            "status": "disabled_this_stage",
            "source_modified": False,
            "hypothesis": request.hypothesis,
            "evidence_ids": list(request.evidence_ids),
            "requested_tests": list(request.requested_tests),
            "next_stage_requires": "reviewed patch, isolated tests and explicit activation",
        }

    def execute(self, *_args, **_kwargs):
        raise RuntimeError("LLM source-code execution and modification are disabled")
