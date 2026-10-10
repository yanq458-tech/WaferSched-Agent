"""Optional isolated HTTP transport; no live LLM experiment is claimed."""
from collections import deque
import json
import subprocess
import sys
from threading import BoundedSemaphore, Lock
from time import monotonic
from .model_endpoint import validated_model_base_url
from .paths import PROJECT_ROOT

_SLOTS, _LOCK, _CALLS = BoundedSemaphore(2), Lock(), deque()


def model_completion(base_url, api_key, body):
    payload = json.dumps({"base_url": validated_model_base_url(base_url), "api_key": api_key,
                          "body": {**body, "max_tokens": 512}}).encode("utf-8")
    if len(payload) > 65536:
        raise ValueError("Model request too large")
    with _LOCK:
        now = monotonic()
        while _CALLS and _CALLS[0] <= now - 3600:
            _CALLS.popleft()
        if len(_CALLS) >= 60:
            raise RuntimeError("Model call budget exhausted")
        _CALLS.append(now)
    if not _SLOTS.acquire(blocking=False):
        raise RuntimeError("Model concurrency exceeded")
    try:
        try:
            completed = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/run_model_worker.py")],
                input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                cwd=PROJECT_ROOT, check=False)
        except subprocess.TimeoutExpired:
            raise TimeoutError("Model request deadline exceeded") from None
        if completed.returncode != 0 or len(completed.stdout) > 32768:
            raise RuntimeError("Model endpoint request failed or exceeded response limit")
        result = json.loads(completed.stdout)
        if not isinstance(result, dict):
            raise ValueError("Model returned a non-object completion")
        return result
    finally:
        _SLOTS.release()
