"""High-level transfers and explicit primitives for physical verification."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    kind: str
    wafer_id: str | None = None
    destination: str | None = None
    source: str | None = None

    @classmethod
    def transfer(cls, wafer_id: str, destination: str, source: str | None = None):
        return cls("transfer", wafer_id, destination, source)

    @classmethod
    def unload(cls, wafer_id: str):
        return cls("unload", wafer_id, "OUT")

    @classmethod
    def wait(cls):
        return cls("wait")

    @classmethod
    def pick(cls, wafer_id: str, source: str):
        return cls("pick", wafer_id, source=source)

    @classmethod
    def move(cls, destination: str):
        return cls("move", destination=destination)

    @classmethod
    def place(cls, wafer_id: str, destination: str):
        return cls("place", wafer_id, destination)
