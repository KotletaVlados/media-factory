"""Command line: publish, delete, login linkedin, records, status, check-staging (design §6).

Everything printed goes through the single redacting output path (`Out`).
Exit codes: 0 all selected targets published (or already published / skipped);
1 at least one target failed or ended unknown; 2 usage error or pre-flight refusal
(nothing was sent).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import math
import os
import sys
import time
import traceback
import urllib.parse
from decimal import Decimal

from poster import __version__, config, facebook, instagram, linkedin, package, rules, state, xapi
from poster.context import Ctx, Result
from poster.http import (ApiError, DryRunTransport, Request, TransportError, UrllibTransport,
                         describe_status)
from poster.redact import Redactor

MODULES = {"facebook": facebook, "instagram": instagram, "x": xapi, "linkedin": linkedin}


class Out:
    def __init__(self, redactor: Redactor, stdout, stderr):
        self.redactor, self.stdout, self.stderr = redactor, stdout, stderr

    def __call__(self, text="", err=False):
        stream = self.stderr if err else self.stdout
        stream.write(self.redactor.redact(text) + "\n")
        stream.flush()


class Usage(Exception):
    """Usage error or pre-flight refusal: exit 2."""


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def _seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a number of seconds") from None
    if not math.isfinite(seconds) or not 0 < seconds <= 86400:
        raise argparse.ArgumentTypeError("timeout must be between 0 and 86400 seconds")
    return seconds


def _count(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if not 1 <= n <= 100000:
        raise argparse.ArgumentTypeError("must be between 1 and 100000")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m poster",
                                description="Publish one post package to Facebook, Instagram, X, LinkedIn.")
    p.add_argument("--env-file", help="env file with credentials (default: MF_ENV_FILE or <repo>/.env)")
    p.add_argument("--state-dir", help="local state folder (default: MF_STATE_DIR or "
                                       "$XDG_STATE_HOME/media-factory/poster)")
    p.add_argument("--debug", action="store_true", help="print redacted tracebacks")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    pub = sub.add_parser("publish", help="publish a post package")
    pub.add_argument("package", help="post package JSON file")
    group = pub.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", help="named target set: " + ", ".join(sorted(config.PROFILES)))
    group.add_argument("--targets", help="comma-separated targets, e.g. fb:kotleta,x")
    pub.add_argument("--dry-run", action="store_true", help="show every request; send nothing")
    pub.add_argument("--library", help="image library folder (default: MF_IMAGE_LIBRARY or "
                                       "<repo>/content/images)")
    pub.add_argument("--force-target", action="append", default=[], metavar="T",
                     help="publish T although the record shows it published or unknown")

    dele = sub.add_parser("delete", help="delete a Facebook Page post this tool published")
    dele.add_argument("--target", required=True, help="fb:NAME")
    dele.add_argument("--post-id", required=True)

    log = sub.add_parser("login", help="one-time login")
    log.add_argument("service", choices=["linkedin"])
    log.add_argument("--port", type=_port, default=linkedin.DEFAULT_PORT)
    log.add_argument("--timeout", type=_seconds, default=600.0)

    rec = sub.add_parser("records", help="show the local post record")
    rec.add_argument("--last", type=_count, default=20)
    rec.add_argument("--package")

    sub.add_parser("status", help="X spend, LinkedIn token expiry, target variables")

    chk = sub.add_parser("check-staging", help="diagnose the Instagram image path (publishes nothing)")
    chk.add_argument("--page", required=True, help="Page name, e.g. kotleta")
    chk.add_argument("image", help="JPEG image path")
    chk.add_argument("--ig-container", metavar="ig:NAME",
                     help="also create (never publish) an Instagram container from the URL")
    return p


class Runtime:
    def __init__(self, args, environ, transport, sleep, clock, out, redactor):
        self.args, self.environ, self.transport = args, environ, transport
        self.sleep, self.clock, self.out, self.redactor = sleep, clock, out, redactor
        self.env_path = config.resolve_env_path(args.env_file, environ)
        self.state_dir = config.resolve_state_dir(args.state_dir, environ)
        self._env = None

    def env(self) -> dict:
        if self._env is None:
            self._env = config.load_env(self.env_path)
            self.redactor.add_env(self._env)
        return self._env

    def ctx(self, *, dry_run=False, ledger=None, package_id="") -> Ctx:
        env = self.env()
        return Ctx(env=env, settings=config.load_settings(env),
                   transport=DryRunTransport() if dry_run else self.transport,
                   redactor=self.redactor,
                   ledger=ledger or state.Ledger(self.state_dir, self.clock),
                   clock=self.clock, sleep=(lambda s: None) if dry_run else self.sleep,
                   dry_run=dry_run, package_id=package_id)


def main(argv=None, *, environ=None, transport=None, sleep=None, clock=None,
         stdout=None, stderr=None) -> int:
    environ = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    redactor = Redactor()
    out = Out(redactor, stdout, stderr)
    parser = build_parser()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    rt = Runtime(args, environ, transport or UrllibTransport(), sleep or time.sleep,
                 clock or utc_now, out, redactor)
    try:
        return COMMANDS[args.command](rt)
    except (Usage, config.ConfigError) as exc:
        out(f"error: {exc}", err=True)
        return 2
    except package.PackageError as exc:
        out("refused: the package is invalid; nothing was sent", err=True)
        for problem in exc.problems:
            out(f"  - {problem}", err=True)
        return 2
    except Exception as exc:  # the single last-resort path; always redacted
        out(f"error: {type(exc).__name__}: {exc}", err=True)
        if args.debug:
            out(traceback.format_exc(), err=True)
        return 1


# ---------------------------------------------------------------- publish

def _image_info(variant):
    return rules.sniff(variant.image_path) if variant and variant.image_path else None


def _money(value: Decimal) -> str:
    return f"${value:.3f}"


def cmd_publish(rt: Runtime) -> int:
    args, out = rt.args, rt.out
    library = config.resolve_library(args.library, rt.environ)
    pkg = package.load(args.package, library)
    targets = config.targets_for(args.profile, args.targets)
    selected_ids = {t.id for t in targets}
    for forced in args.force_target:
        if forced not in selected_ids:
            raise Usage(f"--force-target {forced} is not among the selected targets")
    force = set(args.force_target)
    env = rt.env()
    settings = config.load_settings(env)
    dry = args.dry_run
    records = (state.ReadOnlyRecords if dry else state.Records)(rt.state_dir, rt.clock)
    ledger = (state.ReadOnlyLedger if dry else state.Ledger)(rt.state_dir, rt.clock)
    now = rt.clock()

    problems: list[str] = []
    warnings: list[str] = []
    results: list[Result] = []
    to_run: list[tuple] = []          # (target, variant, checks)
    for t in targets:
        v = pkg.variants.get(t.network)
        if v is None:
            results.append(Result(t.id, t.network, "skipped", note="no variant"))
            continue
        latest = records.latest(pkg.id, t.id)
        if latest and t.id not in force:
            if latest.get("status") == "published":
                results.append(Result(t.id, t.network, "already", post_id=latest.get("post_id"),
                                      url=latest.get("url")))
                continue
            if latest.get("status") == "unknown":
                problems.append(f"{t.id}: the last attempt ({latest.get('ts')}) ended unknown; "
                                f"look at the account, then re-run with --force-target {t.id}")
                continue
        missing = t.missing(env)
        if missing:
            problems.append(f"{t.id}: missing " + ", ".join(missing) + " in the env file")
        text_check = rules.check_text(t.network, v.text)
        info = _image_info(v)
        image_check = rules.check_image(t.network, info)
        for c in (text_check, image_check):
            problems.extend(f"{t.id}: {e}" for e in c.errors)
            warnings.extend(f"{t.id}: {w}" for w in c.warnings)
        if t.network == "linkedin" and not missing:
            errs, warns = linkedin.token_problems(env, now)
            problems.extend(f"{t.id}: {e}" for e in errs)
            warnings.extend(f"{t.id}: {w}" for w in warns)
        to_run.append((t, v, text_check, image_check))

    used = {t.network for t in targets}
    for network in pkg.variants:
        if network not in used:
            warnings.append(f"unused variant: {network} (no selected target)")

    x_month_before = None
    for t, v, *_ in to_run:
        if t.network == "x":
            est = xapi.estimate(v.text, bool(v.image_path), settings)
            try:
                x_month_before = ledger.check(est, settings.cap)
            except state.BudgetExceeded as exc:
                problems.append(f"x: {exc}")

    header = f"package {pkg.id}  " + (f"profile {args.profile}" if args.profile
                                       else f"targets {args.targets}")
    if dry:
        header += "  DRY RUN (nothing is sent, no state is written)"
    out(header)
    for w in warnings:
        out(f"  warning: {w}", err=True)
    if problems:
        out("refused before any network call; nothing was sent:", err=True)
        for p in problems:
            out(f"  - {p}", err=True)
        return 2

    ctx = rt.ctx(dry_run=dry, ledger=ledger, package_id=pkg.id)
    lines: list[str] = []
    for t, v, text_check, image_check in to_run:
        if dry:
            out("")
            out(f"== {t.id} ({t.network}) ==")
            out("text:")
            for row in v.text.split("\n"):
                out("  | " + row)
            for line in text_check.counts + image_check.counts:
                out("  " + line)
            if not v.image_path:
                out("  image: none (text-only)")
            if t.network == "linkedin":
                out("  commentary as sent (little format):")
                for row in rules.linkedin_escape(v.text).split("\n"):
                    out("  | " + row)
            if t.network == "x":
                est = xapi.estimate(v.text, bool(v.image_path), settings)
                items = ", ".join(f"{op} {_money(p)}" for op, p in
                                  xapi.price_items(v.text, bool(v.image_path), settings))
                out(f"  X estimate {_money(est)} ({items}); month {ledger.month()} so far "
                    f"{_money(x_month_before or Decimal(0))} of ${settings.cap:.2f}")
            sent_before = len(ctx.transport.requests)
        try:
            res = MODULES[t.network].publish(v, t, ctx)
        except Exception as exc:  # isolation: one target never stops the others (§9.6)
            res = Result(t.id, t.network, "failed", error=f"{type(exc).__name__}: {exc}")
        # the record and the summary carry only redacted text
        res.error = rt.redactor.redact(res.error) if res.error else None
        res.warnings = [rt.redactor.redact(w) for w in res.warnings]
        if not dry:
            try:
                records.append(res.record_event(pkg.id))
            except OSError as exc:
                res.warnings.append(f"could not write the post record: {exc}")
        if dry:
            out("  requests:")
            for req in ctx.transport.requests[sent_before:]:
                for row in req.describe():
                    for sub in row.split("\n"):
                        out("    " + sub)
        results.append(res)

    # summary, in execution order
    order = {t.id: i for i, t in enumerate(targets)}
    results.sort(key=lambda r: order.get(r.target, 99))
    out("")
    out("summary" + (" (dry run)" if dry else ""))
    width = max(len(r.target) for r in results) if results else 0
    for r in results:
        status = {"published": "published", "failed": "FAILED", "unknown": "UNKNOWN",
                  "skipped": "skipped", "already": "already published"}[r.status]
        if dry and r.status == "published":
            status = "would publish"
        parts = [f"  {r.target.ljust(width)}  {status}"]
        if r.status == "skipped":
            parts.append(f"({r.note})")
        if r.url and not dry:
            parts.append(r.url)
        if r.error:
            parts.append(r.error)
        if r.note and r.status != "skipped" and not dry:
            parts.append(r.note)
        if r.network == "x" and r.status in ("published", "unknown", "failed") and not dry:
            parts.append(f"X month {_money(ledger.month_total())} of ${settings.cap:.2f}")
        out("  ".join(parts))
        for w in r.warnings:
            out(f"    warning: {w}", err=True)
    failed = any(r.status in ("failed", "unknown") for r in results)
    code = 1 if failed else 0
    out(f"exit {code}")
    return code


# ---------------------------------------------------------------- delete

def cmd_delete(rt: Runtime) -> int:
    args, out = rt.args, rt.out
    t = config.parse_target(args.target)
    if t.network != "facebook":
        raise Usage("delete supports Facebook Page posts only (--target fb:NAME)")
    records = state.Records(rt.state_dir, rt.clock)
    events = [r for r in records.all() if r.get("target") == t.id and r.get("post_id") == args.post_id]
    if not events or events[-1].get("status") != "published":
        what = "already deleted" if events and events[-1].get("status") == "deleted" else \
            "not in the post record as published by this tool to " + t.id
        raise Usage(f"refusing to delete {args.post_id}: {what}")
    env = rt.env()
    missing = t.missing(env)
    if missing:
        raise Usage("missing " + ", ".join(missing) + " in the env file")
    ctx = rt.ctx()
    _, token = facebook.page_creds(env, t.name)
    gone, message = facebook.delete_node(ctx, args.post_id, token, "post", pre_read=True)
    if not gone:
        out(f"{t.id}  delete FAILED  {message}", err=True)
        return 1
    records.append({"package": events[-1].get("package"), "target": t.id, "network": "facebook",
                    "status": "deleted", "post_id": args.post_id})
    out(f"{t.id}  {args.post_id}  {message}")
    return 0


# ---------------------------------------------------------------- login

def cmd_login(rt: Runtime) -> int:
    ctx = rt.ctx(ledger=state.ReadOnlyLedger(rt.state_dir, rt.clock))
    return linkedin.login(ctx, rt.env_path, port=rt.args.port, timeout=rt.args.timeout,
                          out=rt.out)


# ---------------------------------------------------------------- records

def cmd_records(rt: Runtime) -> int:
    rows = state.Records(rt.state_dir, rt.clock).all()
    if rt.args.package:
        rows = [r for r in rows if r.get("package") == rt.args.package]
    rows = rows[-rt.args.last:]
    if not rows:
        rt.out("no records")
    for r in rows:
        fields = [r.get("ts", ""), r.get("package", ""), r.get("target", ""), r.get("status", ""),
                  r.get("post_id") or "", r.get("url") or "", r.get("error") or ""]
        rt.out("  ".join(f for f in fields if f))
    return 0


# ---------------------------------------------------------------- status

def cmd_status(rt: Runtime) -> int:
    out = rt.out
    env = rt.env()
    s = config.load_settings(env)
    ledger = state.ReadOnlyLedger(rt.state_dir, rt.clock)
    total = ledger.month_total()
    remaining = max(s.cap - total, Decimal(0))
    image_post = s.price_media_upload + max(s.price_post_with_url, s.price_post_with_media)
    out(f"X {ledger.month()}: spent {_money(total)} of ${s.cap:.2f}, remaining {_money(remaining)}")
    if image_post > 0:
        out(f"  worst case left: {int(remaining // image_post)} image posts "
            f"({_money(image_post)} each)")
    if s.price_post > 0:
        out(f"  or {int(remaining // s.price_post)} text-only posts without links "
            f"({_money(s.price_post)} each)")
    raw = env.get("LINKEDIN_TOKEN_EXPIRES_AT")
    if raw:
        try:
            left = config.parse_utc(raw) - rt.clock()
            out(f"LinkedIn token: {'expired' if left.total_seconds() <= 0 else f'{left.days} day(s) left'}"
                f" (until {config.iso_utc(config.parse_utc(raw))})"
                + ("; run: python3 -m poster login linkedin" if left < _dt.timedelta(days=7) else ""))
        except ValueError:
            out("LinkedIn token: LINKEDIN_TOKEN_EXPIRES_AT is unreadable")
    else:
        out("LinkedIn token: none yet; run: python3 -m poster login linkedin")
    out("targets (variable names only):")
    for t in config.derived_targets(env):
        missing = t.missing(env)
        out(f"  {t.id.ljust(12)} " + ("ready" if not missing else "missing " + ", ".join(missing)))
    out("profiles: " + "; ".join(f"{k} = {', '.join(v)}" for k, v in sorted(config.PROFILES.items())))
    return 0


# ---------------------------------------------------------------- check-staging

def _published_ids(ctx, page_id: str, token: str):
    """Ids on GET /{page_id}/published_posts?limit=10 as a set, or the text 'HTTP n, code c'
    when the edge cannot be read."""
    resp = ctx.send(Request("GET", facebook.graph_url(ctx, page_id, "published_posts",
                                                      limit="10", fields="id",
                                                      access_token=token),
                            secret_fields=("access_token",)))
    if not resp.ok:
        return describe_status(resp)
    return {str(i.get("id", "")) for i in (resp.json().get("data") or []) if isinstance(i, dict)}


def cmd_check_staging(rt: Runtime) -> int:
    args, out = rt.args, rt.out
    page = config.parse_target("fb:" + args.page)
    env = rt.env()
    missing = page.missing(env)
    ig = config.parse_target(args.ig_container) if args.ig_container else None
    if ig and ig.network != "instagram":
        raise Usage("--ig-container takes ig:NAME")
    if ig:
        missing += [m for m in ig.missing(env) if m not in missing]
    if missing:
        raise Usage("missing " + ", ".join(missing) + " in the env file")
    path = os.path.abspath(args.image)
    if not os.path.isfile(path):
        raise Usage(f"image not found: {path}")
    info = rules.sniff(path)
    out(f"image: {os.path.basename(path)} {info.describe()}")
    if info.format != "jpeg":
        out("  warning: Instagram accepts JPEG only; use a JPEG for this check", err=True)
    ctx = rt.ctx(ledger=state.ReadOnlyLedger(rt.state_dir, rt.clock))
    page_id, token = facebook.page_creds(env, page.name)
    ok = True
    photo_id = None
    try:
        before = _published_ids(ctx, page_id, token)
        answer = facebook.stage_photo_answer(ctx, page_id, token, path)
        photo_id = answer["id"]
        out(f"1. staged unpublished photo {photo_id} on {page.id}")
        url = facebook.staged_image_url(ctx, photo_id, token)
        host = urllib.parse.urlsplit(url).hostname
        resp = ctx.send(Request("GET", url, {}, anonymous=True))
        ctype = resp.header("content-type") or "?"
        good = resp.status == 200 and ctype.split(";")[0].strip() == "image/jpeg"
        ok &= good
        out(f"2. anonymous GET of the CDN URL (host {host}): {resp.status}, {ctype}, "
            f"{len(resp.body)} bytes -> {'OK' if good else 'NOT OK'}")
        after = _published_ids(ctx, page_id, token)
        if isinstance(after, str) or isinstance(before, str):
            absent, verdict = False, f"unreadable ({after if isinstance(after, str) else before})"
        else:
            # a photo that became a Page post is listed under a new post id, not the photo id
            new = sorted(after - before) + ([str(answer["post_id"])] if answer.get("post_id") else [])
            absent = not new
            verdict = "yes" if absent else f"NO (new post {', '.join(new)})"
        ok &= absent
        out(f"3. photo absent from the Page's published posts (last 10): {verdict}")
        if ig:
            ig_page_id, ig_token = facebook.page_creds(env, ig.name)
            container = instagram.create_container(ctx, instagram.ig_user_id(env, ig.name),
                                                   ig_token, url, None)
            out(f"4. Instagram container {container} created (media_publish is never called)")
            instagram.wait_finished(ctx, container, ig_token)
            out("   container FINISHED; it expires unpublished after 24 hours")
    except (ApiError, TransportError) as exc:
        ok = False
        out(f"check failed: {exc}", err=True)
    finally:
        if photo_id:
            gone, message = facebook.delete_node(ctx, photo_id, token, "staging photo")
            ok &= gone
            out(f"cleanup: staging photo {photo_id} {message}")
    out("check-staging " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


COMMANDS = {"publish": cmd_publish, "delete": cmd_delete, "login": cmd_login,
            "records": cmd_records, "status": cmd_status, "check-staging": cmd_check_staging}
