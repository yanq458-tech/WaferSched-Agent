"""Real OpenAI-format HTTP, isolated credentials, auditable calls and cost bounds."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from wafer_sched.infrastructure.model_endpoint import validated_model_base_url


ENV_KEYS = ("ASSISTANT_LLM_BASE_URL", "ASSISTANT_LLM_MODEL", "ASSISTANT_LLM_API_KEY")


def local_configuration(path, environ=None):
    """Read project .env; process environment is never implicitly consulted."""
    values = dict(environ or {})
    path = Path(path)
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if name not in ENV_KEYS:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name] = value
    return {name: values.get(name, "") for name in ENV_KEYS}


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 45.0
    max_output_tokens: int = 1536
    input_peak_usd_per_million: float = 0.30
    output_peak_usd_per_million: float = 1.20
    cached_input_peak_usd_per_million: float = 0.006

    def __post_init__(self):
        if not (
            type(self.max_output_tokens) is int and 1 <= self.max_output_tokens <= 4096
        ):
            raise ValueError("Invalid maximum output tokens")
        if not (
            math.isfinite(self.timeout_seconds) and 1 <= self.timeout_seconds <= 60
        ):
            raise ValueError("Invalid API timeout")
        for value in [
            self.input_peak_usd_per_million,
            self.output_peak_usd_per_million,
            self.cached_input_peak_usd_per_million,
        ]:
            if not (math.isfinite(value) and value > 0):
                raise ValueError("Pricing rates must be finite positive bounds")
        if self.base_url:
            validated_model_base_url(self.base_url)

    @classmethod
    def from_local(cls, path, overrides=None):
        env = local_configuration(path)
        # Overrides configure public settings only, never an embedded credential.
        opts = dict(overrides or {})
        if "api_key" in opts:
            raise ValueError("Credentials must come from environment or ignored .env")
        return cls(
            base_url=env[ENV_KEYS[0]],
            model=env[ENV_KEYS[1]],
            api_key=env[ENV_KEYS[2]],
            **opts,
        )

    @property
    def configured(self):
        return bool(self.base_url and self.model and self.api_key)

    def public(self):
        return {
            "base_url": self.base_url,
            "model": self.model,
            "configured": self.configured,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "pricing": {
                "input_peak_usd_per_million": self.input_peak_usd_per_million,
                "output_peak_usd_per_million": self.output_peak_usd_per_million,
                "cached_input_peak_usd_per_million": self.cached_input_peak_usd_per_million,
                "basis": "conservative_peak_estimate_not_provider_invoice",
            },
        }


class LLMUnavailable(RuntimeError):
    """Public error contains only a classification, never provider response text."""


def append_jsonl(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def real_http(settings, body, deadline):
    payload = {
        "base_url": validated_model_base_url(settings.base_url),
        "api_key": settings.api_key,
        "body": body,
        "timeout": max(0.1, deadline - 0.5),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "wafer_sched.langgraph_agent.http_worker"],
        input=json.dumps(payload).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=deadline,
        check=False,
    )
    if proc.returncode or len(proc.stdout) > 262144:
        raise LLMUnavailable("http_worker_failed_or_response_too_large")
    return json.loads(proc.stdout)


class LLMClient:
    evidence_source = "real_api"

    def __init__(self, settings, limits, log_path, *, transport=None):
        self.settings, self.limits, self.log_path = settings, limits, Path(log_path)
        self.transport = transport or real_http
        self.evidence_source = "unit_test_mock" if transport else "real_api"
        self.records = []
        if self.log_path.exists():
            self.records = [
                json.loads(line)
                for line in self.log_path.read_text(encoding="utf-8").splitlines()
                if line
            ]

    def _redact(self, value):
        if isinstance(value, str):
            return (
                value.replace(self.settings.api_key, "[REDACTED]")
                if self.settings.api_key
                else value
            )
        if isinstance(value, list):
            return [self._redact(v) for v in value]
        if isinstance(value, dict):
            return {
                k: self._redact(v)
                for k, v in value.items()
                if k.lower() not in {"api_key", "authorization", "reasoning_content"}
            }
        return value

    def totals(self):
        usage = [r for r in self.records if r.get("usage")]
        return {
            "calls": len(self.records),
            "successful_api_calls": sum(
                r["status"] == "completed" and r["evidence_source"] == "real_api"
                for r in self.records
            ),
            "reported_total_tokens": sum(r["usage"]["total_tokens"] for r in usage),
            "reported_prompt_tokens": sum(r["usage"]["prompt_tokens"] for r in usage),
            "reported_completion_tokens": sum(
                r["usage"]["completion_tokens"] for r in usage
            ),
            "calls_with_missing_usage": sum(
                r["status"] == "completed" and not r.get("usage") for r in self.records
            ),
            "budget_charged_tokens": sum(
                r.get("budget_charged_tokens", 0) for r in self.records
            ),
            "estimated_peak_api_usd": sum(
                r.get("estimated_peak_api_usd", 0) for r in self.records
            ),
            "budget_charged_usd": sum(
                r.get("budget_charged_usd", 0) for r in self.records
            ),
            "llm_wall_seconds": sum(r["wall_seconds"] for r in self.records),
        }

    def call(self, stage, context, schema, remaining_seconds):
        started = perf_counter()
        schema_json = schema.model_json_schema()
        system = (
            "You are a mathematical experiment researcher. Return ONLY a JSON object matching "
            "the schema. Choose only allowlisted scenarios, methods, budgets and model IDs. "
            "Never emit executable code, commands or invented measurements. Verification and "
            "optimality are determined by the original Simulator and solver, not your claims. "
            "Use observed histories to propose a testable hypothesis; explain failures. "
            "Aim to obtain at least five meaningful experiment rounds if budget and candidate "
            "space permit, but you may stop futile research. Distinguish early discovery from "
            "total computation cost. Schema: "
            + json.dumps(schema_json, separators=(",", ":"))
        )
        body = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": self.settings.max_output_tokens,
            "thinking": {"type": "disabled"},
            "temperature": 0,
        }
        # UTF-8 bytes conservatively bound input tokens; include message framing.
        input_bound = sum(
            len(m["content"].encode("utf-8")) + 128 for m in body["messages"]
        )
        token_reserve = input_bound + self.settings.max_output_tokens
        cost_reserve = (
            input_bound * self.settings.input_peak_usd_per_million
            + self.settings.max_output_tokens
            * self.settings.output_peak_usd_per_million
        ) / 1e6
        total = self.totals()
        record = {
            "call_id": f"llm-{len(self.records) + 1:04d}",
            "stage": stage,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": self.settings.model,
            "endpoint": self.settings.base_url,
            "evidence_source": self.evidence_source,
            "request": self._redact(body),
            "status": "not_called",
            "usage": None,
            "wall_seconds": 0,
            "http_status": None,
            "response": None,
            "reserved_token_bound": token_reserve,
            "reserved_cost_bound_usd": cost_reserve,
            "budget_charged_tokens": 0,
            "budget_charged_usd": 0,
            "estimated_peak_api_usd": 0,
        }
        error = None
        network_started = False
        try:
            if not self.settings.configured:
                raise LLMUnavailable("llm_configuration_unavailable")
            if (
                total["calls"] >= self.limits.max_llm_calls
                or total["budget_charged_tokens"] + token_reserve
                > self.limits.max_total_tokens
                or total["budget_charged_usd"] + cost_reserve > self.limits.max_api_usd
            ):
                raise LLMUnavailable("llm_call_token_or_fee_budget_exhausted")
            if remaining_seconds <= 1:
                raise LLMUnavailable("session_wall_budget_exhausted")
            network_started = True
            envelope = self.transport(
                self.settings,
                body,
                min(self.settings.timeout_seconds, remaining_seconds),
            )
            record["http_status"] = envelope.get("http_status")
            if envelope.get("provider_error"):
                record["provider_error"] = self._redact(envelope["provider_error"])
            if envelope.get("error"):
                raise LLMUnavailable(envelope["error"])
            completion = envelope["response"]
            record["response"] = self._redact(completion)
            content = completion["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content.encode()) > 32768:
                raise LLMUnavailable("invalid_or_oversize_structured_content")
            usage = completion.get("usage")
            if usage:
                fields = [
                    usage.get(k)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                ]
                if not all(type(v) is int and v >= 0 for v in fields):
                    raise LLMUnavailable("invalid_usage_accounting")
                record["usage"] = self._redact(usage)
                cached = min(
                    usage.get("prompt_cache_hit_tokens", 0), usage["prompt_tokens"]
                )
                estimate = (
                    (usage["prompt_tokens"] - cached)
                    * self.settings.input_peak_usd_per_million
                    + cached * self.settings.cached_input_peak_usd_per_million
                    + usage["completion_tokens"]
                    * self.settings.output_peak_usd_per_million
                ) / 1e6
                record.update(
                    budget_charged_tokens=usage["total_tokens"],
                    estimated_peak_api_usd=estimate,
                    budget_charged_usd=estimate,
                )
            else:
                record.update(
                    budget_charged_tokens=token_reserve, budget_charged_usd=cost_reserve
                )
            # Successful HTTP completion remains genuine evidence even if its JSON
            # subsequently fails ProposalValidator. Keep the raw response for audit.
            record["status"] = "completed"
            record["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
            value = self._redact(json.loads(content))
        except Exception as exc:
            error = exc
            if record["status"] != "completed":
                record["status"] = "failed" if network_started else "not_called"
            record["error_type"] = type(exc).__name__
            record["error_code"] = (
                str(exc) if isinstance(exc, LLMUnavailable) else "invalid_response"
            )
            # Ambiguous transport failures reserve the possible charge; explicit
            # auth/rate-limit rejection has no successful completion usage.
            if (
                network_started
                and record["http_status"] not in {400, 401, 402, 403, 404, 429}
                and not record.get("usage")
            ):
                record.update(
                    budget_charged_tokens=token_reserve, budget_charged_usd=cost_reserve
                )
        finally:
            record["wall_seconds"] = perf_counter() - started
            record = self._redact(record)
            append_jsonl(self.log_path, record)
            self.records.append(record)
        if error:
            raise LLMUnavailable(record.get("error_code", "llm_failure")) from None
        return value, record
