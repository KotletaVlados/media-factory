"""Factory test harness: a temp content folder (stock + rules), a factory state folder, a fake
poster entry point and a frozen clock, on top of the poster's harness (network guard, canary
secrets in a fake env file)."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import threading

from poster import state as poster_state
from factory import cli as fcli
from tests.base import PosterTestCase, make_jpeg

UTC = dt.timezone.utc


def utc(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=UTC)


class FakePoster:
    """Stands in for poster.cli.main. For each call it records the argv and, like the poster,
    appends one record row per target to posts.jsonl, then returns the exit code.

    `statuses` maps target -> status (default published). `script` is a list of per-call
    overrides: an int exit code, an exception instance to raise, or a callable."""

    def __init__(self, test, statuses=None, code=None, output=""):
        self.test = test
        self.calls: list[list[str]] = []
        self.statuses = statuses or {}
        self.code = code
        self.output = output
        self.before_return = None      # optional hook run inside the call (races, blocking)

    def targets(self, argv) -> list[str]:
        return argv[argv.index("--targets") + 1].split(",")

    def package_id(self, argv) -> str:
        path = argv[argv.index("publish") + 1]
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("id") or os.path.basename(path)[:-5]

    def __call__(self, argv, *, environ, stdout, stderr, clock):
        self.calls.append(list(argv))
        if self.before_return:
            self.before_return(self)
        if self.output:
            stdout.write(self.output)
        if self.code == 2:
            return 2
        records = poster_state.Records(environ["MF_STATE_DIR"], clock)
        pid = self.package_id(argv)
        failed = False
        for t in self.targets(argv):
            status = self.statuses.get(t, "published")
            failed |= status in ("failed", "unknown")
            network = {"fb": "facebook", "ig": "instagram"}.get(t.split(":")[0], t)
            records.append({"package": pid, "target": t, "network": network, "status": status,
                            "post_id": f"id-{pid}-{t}"})
            stdout.write(f"  {t}  {status}\n")
        return self.code if self.code is not None else (1 if failed else 0)


class FactoryTestCase(PosterTestCase):
    def setUp(self):
        super().setUp()
        self.content = os.path.join(self.root, "content")
        self.stock = os.path.join(self.content, "stock")
        self.fstate = os.path.join(self.root, "factory-state")
        os.makedirs(self.stock)
        self.environ.update({"MF_CONTENT_DIR": self.content, "MF_FACTORY_STATE_DIR": self.fstate,
                             "TZ": "Europe/Berlin"})
        self.image("square.jpg", make_jpeg(1080, 1080))
        self.poster = FakePoster(self)
        self.addCleanup(self._assert_no_canary_in_factory_state)

    def _assert_no_canary_in_factory_state(self):
        for folder in (self.fstate, self.content):
            if os.path.isdir(folder):
                for dirpath, _, files in os.walk(folder):
                    for f in files:
                        with open(os.path.join(dirpath, f), encoding="utf-8",
                                  errors="replace") as fh:
                            self.assert_no_canary(fh.read())

    # ------------------------------------------------------------ fixtures

    def folder(self, name: str, lane: str = "photo", title: str | None = None) -> str:
        path = os.path.join(self.stock, name)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "folder.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "title": title or name.title(), "lane": lane}, fh)
        return path

    def stock_package(self, folder: str, name: str, variants: dict | None = None,
                      approved: bool = True, **top) -> str:
        if variants is None:
            variants = {"facebook": {"text": f"{name} long text", "image": "square.jpg"},
                        "instagram": {"text": f"{name} caption", "image": "square.jpg"},
                        "linkedin": {"text": f"{name} angle", "image": "square.jpg"},
                        "x": {"text": f"{name} quote", "image": "square.jpg"}}
        data = {"schema": 1, "id": name, "theme": "test", "variants": variants}
        if approved:
            data["meta"] = {"approved_by_operator": "2026-11-10"}
        data.update(top)
        path = os.path.join(self.stock, folder, name + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return path

    def write_rules(self, rules: list, limits: dict | None = None) -> str:
        doc = {"schema": 1, "rules": rules}
        if limits:
            doc["limits"] = limits
        path = os.path.join(self.content, "rules.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        return path

    def rules_hash(self) -> str:
        with open(os.path.join(self.content, "rules.json"), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def rules_doc(self) -> dict:
        with open(os.path.join(self.content, "rules.json"), encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def rule(rid, folder, targets, days, hours, status="active", tz="Europe/Berlin",
             since="2026-11-01T00:00:00Z"):
        data = {"id": rid, "folder": folder, "targets": targets, "days": days, "hours": hours,
                "timezone": tz, "status": status}
        if status == "active" and since:
            data["active_since"] = since
        return data

    def ledger_spent(self, amount: str, month: str = "2026-11", package: str = "earlier"):
        os.makedirs(self.state_dir, exist_ok=True)
        poster_state.append_jsonl(os.path.join(self.state_dir, "x-ledger.jsonl"), [
            {"ts": f"{month}-01T00:00:00Z", "month": month, "rid": f"r-{package}-{amount}",
             "op": "post", "price": amount, "package": package, "status": "reserved"},
            {"ts": f"{month}-01T00:00:01Z", "month": month, "rid": f"r-{package}-{amount}",
             "status": "ok"}])

    def record(self, package: str, target: str, status: str, ts: str):
        os.makedirs(self.state_dir, exist_ok=True)
        network = {"fb": "facebook", "ig": "instagram"}.get(target.split(":")[0], target)
        poster_state.append_jsonl(os.path.join(self.state_dir, "posts.jsonl"), [
            {"ts": ts, "package": package, "target": target, "network": network,
             "status": status}])

    # ------------------------------------------------------------ running

    def factory(self, *argv, publish=None):
        out, err = io.StringIO(), io.StringIO()
        code = fcli.main(list(argv), environ=self.environ, clock=self.clock, stdout=out,
                         stderr=err, publish=publish or self.poster)
        self.outputs += [out.getvalue(), err.getvalue()]
        return code, out.getvalue(), err.getvalue()

    def journal(self) -> list[dict]:
        path = os.path.join(self.fstate, "runs.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def statuses(self) -> dict:
        """slot -> list of statuses in journal order."""
        out: dict = {}
        for row in self.journal():
            out.setdefault(row["slot"], []).append(row["status"])
        return out


def run_in_thread(fn):
    box = {}

    def target():
        box["result"] = fn()
    t = threading.Thread(target=target)
    t.start()
    return t, box
