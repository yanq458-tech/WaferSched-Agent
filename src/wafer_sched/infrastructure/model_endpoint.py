"""Operator-configured endpoints, without credentials in URLs."""
from urllib.parse import urlsplit


def validated_model_base_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("Model endpoint must be an HTTP(S) URL without credentials, query or fragment")
    parsed.port
    return value.rstrip("/")
