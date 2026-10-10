"""Closed proposal schema: no arbitrary paths, code, commands or measured results."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re

from ..policies.rules import POLICIES

METHODS = ("rule", "cpsat", "rl")


def config_hash(config):
    return hashlib.sha256(json.dumps(config.to_dict(), sort_keys=True).encode()).hexdigest()


def positive(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field} must be finite and positive")


@dataclass(frozen=True)
class ExperimentProposal:
    experiment_id: str
    scenario_id: str
    proposed_method: str
    parameters: dict
    expected_reason: str
    evidence_from_history: list[str]
    estimated_budget: float
    selection_reason: str

    def __post_init__(self):
        for field in ("experiment_id", "scenario_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                raise ValueError(f"Unsafe {field}")
        if self.proposed_method not in METHODS or type(self.parameters) is not dict:
            raise ValueError("Unsupported method or parameters")
        fields = {"rule": {"policy"}, "cpsat": {"max_seconds"}, "rl": {"model_id"}}
        if set(self.parameters) != fields[self.proposed_method]:
            raise ValueError("Parameters must exactly match the selected Skill schema")
        if self.proposed_method == "rule" and self.parameters["policy"] not in POLICIES:
            raise ValueError("Rule is not registered")
        if self.proposed_method == "cpsat":
            positive(self.parameters["max_seconds"], "max_seconds")
        if self.proposed_method == "rl" and (not isinstance(self.parameters["model_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.parameters["model_id"])):
            raise ValueError("Unsafe model identifier")
        positive(self.estimated_budget, "estimated_budget")
        for name in ("expected_reason", "selection_reason"):
            if not isinstance(getattr(self, name), str) or not 1 <= len(getattr(self, name)) <= 2000:
                raise ValueError(f"Invalid {name}")
        if (not isinstance(self.evidence_from_history, list)
                or any(not isinstance(item, str) or len(item) > 80 for item in self.evidence_from_history)
                or len(self.evidence_from_history) > 100):
            raise ValueError("Invalid evidence identifiers")

    @classmethod
    def from_dict(cls, data):
        if type(data) is not dict or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("Proposal has missing/unknown fields")
        return cls(**data)

    def to_dict(self):
        return asdict(self)

    @property
    def signature(self):
        return self.proposed_method + ":" + json.dumps(self.parameters, sort_keys=True)

    def validate_context(self, scenario_id, history, candidates, remaining, max_experiment_seconds):
        # Reconstruct to detect any mutation of nested parameters after construction.
        self.from_dict(self.to_dict())
        if self.scenario_id != scenario_id:
            raise ValueError("Proposal targets a different scenario")
        known = {row["proposal"]["experiment_id"] for row in history}
        if not set(self.evidence_from_history) <= known:
            raise ValueError("Proposal cites nonexistent evidence")
        if self.experiment_id in known:
            raise ValueError("Experiment identifier already committed")
        if self.signature in {ExperimentProposal.from_dict(row["proposal"]).signature for row in history}:
            raise ValueError("Duplicate experiment without new parameters")
        if self.estimated_budget > min(remaining, max_experiment_seconds):
            raise ValueError("Proposal exceeds the remaining/single experiment budget")
        if self.proposed_method == "cpsat":
            if self.parameters["max_seconds"] not in candidates["cp_budgets"]:
                raise ValueError("CP budget is not allowlisted")
        elif self.proposed_method == "rl":
            if self.parameters["model_id"] not in candidates["models"]:
                raise ValueError("Model identifier is not in the read-only catalogue")
        elif self.parameters["policy"] not in candidates["rules"]:
            raise ValueError("Rule not in this study's candidate set")
