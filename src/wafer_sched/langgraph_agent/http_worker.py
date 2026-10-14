"""Fixed HTTP worker. The secret travels on stdin and is never logged."""

import json
import re
import sys
import urllib.error
import urllib.request

from wafer_sched.infrastructure.model_endpoint import validated_model_base_url


def safe_provider_error(raw, api_key):
    """Only export sanitized error type/code/message; never headers or raw bodies."""
    try:
        body = json.loads(raw)
        error = body.get("error") if isinstance(body, dict) else None
    except (ValueError, UnicodeError):
        error = None
    if not isinstance(error, dict):
        return {
            "type": None,
            "code": None,
            "message": "Non-JSON or nonstandard error body omitted",
        }

    def clean(value):
        if not isinstance(value, (str, int)):
            return None
        text = str(value)
        if api_key:
            text = text.replace(api_key, "[REDACTED]")
        text = re.sub(r"(?i)\bBearer\s+\S+", "[REDACTED_AUTHENTICATION]", text)
        text = re.sub(r"\bsk-[A-Za-z0-9_.*-]+", "[REDACTED_CREDENTIAL]", text)
        text = re.sub(
            r"(?i)((?:api[ _-]*key|authorization|access[ _-]*token|password|secret)\s*[:=]\s*)[^\s,;]+",
            r"\1[REDACTED]",
            text,
        )
        return text[:2048]

    return {name: clean(error.get(name)) for name in ("type", "code", "message")}


def main():
    data = sys.stdin.buffer.read(131073)
    if len(data) > 131072:
        raise ValueError("Request too large")
    payload = json.loads(data)
    url = validated_model_base_url(payload["base_url"]) + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload["body"]).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + payload["api_key"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=payload["timeout"]) as response:
            raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("Response too large")
            result = {"http_status": response.status, "response": json.loads(raw)}
    except urllib.error.HTTPError as exc:
        raw = exc.read(16385)
        result = {
            "http_status": exc.code,
            "error": f"http_{exc.code}",
            "provider_error": safe_provider_error(raw, payload["api_key"])
            if len(raw) <= 16384
            else {"type": None, "code": None, "message": "Oversize error body omitted"},
        }
    except Exception as exc:
        result = {"http_status": None, "error": "transport_" + type(exc).__name__}
    sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))


if __name__ == "__main__":
    main()
