"""Fixed subprocess worker; credentials arrive on stdin, never command line."""
import json
import sys
import urllib.request
from .model_endpoint import validated_model_base_url


def main():
    payload = sys.stdin.buffer.read(65537)
    if len(payload) > 65536:
        raise ValueError("Request too large")
    data = json.loads(payload)
    url = validated_model_base_url(data["base_url"]) + "/chat/completions"
    request = urllib.request.Request(url, data=json.dumps(data["body"]).encode("utf-8"),
        headers={"Authorization": "Bearer " + data["api_key"], "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=4) as response:
        body = response.read(32769)
    if len(body) > 32768:
        raise ValueError("Response too large")
    sys.stdout.buffer.write(body)


if __name__ == "__main__":
    main()
