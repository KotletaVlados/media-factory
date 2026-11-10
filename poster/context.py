"""Run context handed to every target module, and the per-target result (design §4)."""

from __future__ import annotations

from dataclasses import dataclass, field

from poster.config import Settings
from poster.redact import Redactor


@dataclass
class Ctx:
    env: dict
    settings: Settings
    transport: object          # .send(Request) -> Response
    redactor: Redactor
    ledger: object             # state.Ledger
    clock: object              # () -> aware UTC datetime
    sleep: object              # (seconds) -> None
    dry_run: bool = False
    package_id: str = ""

    def send(self, req):
        return self.transport.send(req)


@dataclass
class Result:
    target: str
    network: str
    status: str                      # published | failed | unknown | skipped | already
    post_id: str | None = None
    url: str | None = None
    error: str | None = None
    warnings: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    note: str | None = None          # one short line for the summary

    def record_event(self, package_id: str) -> dict:
        event = {"package": package_id, "target": self.target, "network": self.network,
                 "status": self.status, "post_id": self.post_id, "url": self.url,
                 "error": self.error, "extra": dict(self.extra)}
        return event
