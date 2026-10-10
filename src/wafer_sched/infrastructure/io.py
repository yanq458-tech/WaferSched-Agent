"""Original stdlib adapter: durable publication and safe experiment identifiers.

Interface roles were identified in the source audit; no railway module is copied.
"""
from datetime import datetime, timezone
import ctypes
import json
import os
from pathlib import Path
import re
import tempfile
import uuid


def safe_run_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ValueError("Unsafe run id")
    return value


def new_run_id(requested=None):
    return safe_run_id(requested if requested is not None else
        datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])


def durable_replace(source, destination):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if os.name == "nt":
        from ctypes import wintypes
        native = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        native.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        native.restype = wintypes.BOOL
        if not native(str(source), str(destination), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(source, destination)
        for directory in {source.parent, destination.parent}:
            handle = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)


def atomic_record(path, state):
    path = Path(path)
    handle, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        durable_replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
