"""HTML of the panel: the shared shell and one function per tab (design factory.md §11).

Pages are f-strings; every value that is not a fixed string from `strings.py` goes through
`esc` (html.escape), and every string from records, journals, stats or core messages has
already passed the snapshot's Redactor. The server redacts the finished page once more.
CSP forbids inline styles and scripts, so sizes that depend on data (bars, rings,
sparklines) are SVG attributes.
"""

from __future__ import annotations

import calendar as _calendar
import datetime as _dt
import html
import json
import math
import urllib.parse

from poster import config
from factory import planner, ruleset as fruleset
from factory.authoring import photos as fphotos
from factory.panel import model as M, strings as S

DOMAINS = {"facebook": "fb", "instagram": "ig", "x": "x", "linkedin": "in", "telegram": "tg",
           "threads": "th", "youtube": "yt", "tiktok": "tt", "pinterest": "pi"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def qs(**params) -> str:
    items = [(k, v) for k, v in params.items() if v not in (None, "", False)]
    return ("?" + urllib.parse.urlencode(items)) if items else ""


class Ctx:
    """What every page needs: the snapshot, the request path and query, the CSRF token."""

    def __init__(self, snap, path: str, query: dict, csrf: str, probe: bool = False, author=None):
        self.snap, self.path, self.query, self.csrf, self.probe = snap, path, query, csrf, probe
        self.author = author

    def q(self, name: str, default: str = "") -> str:
        values = self.query.get(name) or [default]
        return values[0]


# ---------------------------------------------------------------- small parts

def disc(network: str, dim: bool = False) -> str:
    cls = f"disc n-{DOMAINS.get(network, 'x')}" + (" dim" if dim else "")
    return f'<span class="{cls}">{esc(S.MONO.get(network, "?"))}</span>'


def target_chip(target: str) -> str:
    return (f'<span class="tchip">{disc(M.network_of(target))}'
            f'<span class="mono">{esc(target)}</span></span>')


def bar(fill: float, kind: str = "good", label: str = "") -> str:
    width = max(0.0, min(1.0, fill)) * 100
    return (f'<svg class="bar" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">'
            f'<rect class="bar-bg" width="100" height="4" rx="2"/>'
            f'<rect class="bar-fg {kind}" width="{width:.1f}" height="4" rx="2"/></svg>')


def img_url(entry, ref: str) -> str:
    return "/img" + qs(folder=entry.folder, file=entry.file, ref=ref)


def tile(entry, network: str | None = None, cls: str = "tile") -> str:
    ref = M.image_ref(entry, network)
    if ref:
        return (f'<img class="{cls}" src="{esc(img_url(entry, ref))}" alt="" loading="lazy" '
                f'decoding="async">')
    text = M.first_line(M.variant_text(entry, network), 60) if entry else ""
    return f'<span class="{cls} tile-text" aria-hidden="true">{esc(text)}</span>'


def money(value) -> str:
    return f"{value:.2f}"


def hidden(ctx: Ctx, **fields) -> str:
    out = f'<input type="hidden" name="csrf" value="{esc(ctx.csrf)}">'
    for k, v in fields.items():
        out += f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">'
    return out


def alert(label: str, problems: list, cls: str = "alert") -> str:
    if not problems:
        return ""
    items = "".join(f"<li><span class=\"alert-label\">{esc(label)}</span> "
                    f"<span class=\"core\">{esc(p)}</span></li>" for p in problems)
    return f'<ul class="{cls}" role="alert">{items}</ul>'


def chips(ctx: Ctx, counts: dict, total: int, active: str, base: str, keep: dict) -> str:
    out = []
    for net, label, n in [("", S.ALL, total)] + [
            (net, S.MONO[net], counts[net]) for net in S.BUILT if counts.get(net)]:
        href = base + qs(net=net, **keep)
        current = ' aria-current="true"' if net == active else ""
        icon = disc(net) if net else ""
        name = esc(label) if not net else ""
        out.append(f'<a class="chip{" on" if net == active else ""}" href="{esc(href)}"{current}>'
                   f'{icon}{name}<span class="mono n">{S.group(n)}</span></a>')
    return f'<nav class="chips" aria-label="Сети">{"".join(out)}</nav>'


# ---------------------------------------------------------------- shell

def page(ctx: Ctx, tab: str, body: str, *, sub: str = "", sub_right: str = "",
         title: str = "", scripts: tuple = ()) -> str:
    snap = ctx.snap
    tabs = []
    for key, label in S.TABS:
        current = ' aria-current="page"' if key == tab else ""
        tabs.append(f'<a class="tab{" on" if key == tab else ""}" href="/{key}"{current}>'
                    f'{esc(label)}</a>')
    tabs.append(f'<span class="tab off" aria-disabled="true">{esc(S.DIALOGS_OFF)}</span>')
    status = ""
    strip = ""
    if snap is not None and snap.inputs is not None and snap.plan is not None:
        status, strip = _status(ctx, tab)
    probe = "".join(f'<script src="/static/{esc(name)}" defer></script>\n' for name in scripts)
    probe += '<script src="/static/probe.js" defer></script>' if ctx.probe else ""
    sub_html = ""
    if sub or sub_right:
        sub_html = (f'<div class="sub"><p class="sub-left">{sub}</p>'
                    f'<div class="sub-right">{sub_right}</div></div>')
    heading = esc(title or dict(S.TABS).get(tab, "Диалоги"))
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading} · {esc(S.APP_TITLE)}</title>
<link rel="stylesheet" href="/static/panel.css">
<script src="/static/panel.js" defer></script>
{probe}
</head>
<body>
<div class="app">
<header class="topbar">
<nav class="tabs" aria-label="{esc(S.NAV_LABEL)}">{"".join(tabs)}</nav>
{status}
</header>
{strip}
{sub_html}
<main class="main main-{esc(tab)}">
<h1 class="sr">{heading}</h1>
{body}
</main>
</div>
</body>
</html>
"""


def _status(ctx: Ctx, tab: str) -> tuple:
    snap = ctx.snap
    top = M.topbar(snap)
    is_open = ctx.q("attention") == "1"
    keep = {k: v[0] for k, v in ctx.query.items() if k != "attention" and v}
    open_href = ctx.path + qs(**keep, attention="1")
    close_href = ctx.path + qs(**keep)
    n = top["attention"]
    bell = (f'<a class="bell{" has" if n else ""}" href="{esc(close_href if is_open else open_href)}" '
            f'data-toggle="attention" aria-controls="attention" '
            f'aria-expanded="{"true" if is_open else "false"}">'
            f'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5a4 4 0 0 0-4 4v2.7L2.6 '
            f'11h10.8L12 8.2V5.5a4 4 0 0 0-4-4Zm-1.6 11a1.6 1.6 0 0 0 3.2 0Z"/></svg>'
            f'<span class="sr">{esc(S.ATTENTION)}</span>'
            f'<span class="badge mono">{n}</span></a>')
    cap = top["cap"] or 1
    spent, planned = top["spent"], top["planned"]
    xbar = (f'<svg class="bar xbar" viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true">'
            f'<rect class="bar-bg" width="100" height="4" rx="2"/>'
            f'<rect class="bar-fg plan" width="{min(100, float((spent + planned) / cap * 100)):.1f}" '
            f'height="4" rx="2"/>'
            f'<rect class="bar-fg good" width="{min(100, float(spent / cap * 100)):.1f}" height="4" '
            f'rx="2"/></svg>')
    xtext = S.X_METER.format(month=top["month"], spent=money(spent), cap=money(top["cap"]))
    status = (f'<div class="status">{bell}'
              f'<span class="xm">{xbar}<span class="mono">{esc(xtext)} · '
              f'{esc(S.X_PLAN.format(planned=money(planned)))}</span></span>'
              f'<span class="mono{" red" if top["linkedin_bad"] else ""}">{esc(top["linkedin"])}</span>'
              f'<span class="mono{" red" if top["timer_bad"] else ""}">{esc(top["timer"])}</span>'
              f'</div>')
    items = "".join(
        f'<li><a href="{esc(M.attention_link(snap, a))}"><span class="core">{esc(a)}</span></a></li>'
        for a in snap.attention) or f"<li>{esc(S.ATTENTION_NONE)}</li>"
    strip = (f'<section id="attention" class="attn"{"" if is_open else " hidden"} '
             f'aria-labelledby="attention-h"><div class="attn-head"><h2 id="attention-h">'
             f'{esc(S.ATTENTION)} · <span class="mono">{n}</span></h2>'
             f'<a class="btn" href="{esc(close_href)}" data-toggle="attention">'
             f'{esc(S.ATTENTION_HIDE)}</a></div><ul>{items}</ul></section>')
    return status, strip


def error_block(title: str, problems: list, hint: str = "") -> str:
    items = "".join(f'<li class="core">{esc(p)}</li>' for p in problems)
    hint_html = f'<p class="muted">{esc(hint)}</p>' if hint else ""
    return (f'<section class="error" role="alert"><h2>{esc(title)}</h2>'
            f'<ul>{items}</ul>{hint_html}</section>')


def env_error_page(ctx: Ctx, tab: str) -> str:
    snap = ctx.snap
    title = S.ERR_ENV_MISSING if snap.env_missing else S.ERR_ENV_BAD
    return page(ctx, tab, error_block(title, [snap.env_error], S.HOW_ENV))


def other_error_page(ctx: Ctx, message: str) -> str:
    return page(ctx, "error", error_block(S.ERR_OTHER, [message]), title=S.ERR_OTHER)


def not_found_page(ctx: Ctx) -> str:
    return page(ctx, "error", error_block(S.NOT_FOUND, [ctx.path]), title=S.NOT_FOUND)


def rules_error_page(ctx: Ctx, tab: str) -> str:
    return page(ctx, tab, error_block(S.ERR_RULES, ctx.snap.rules_error, S.ERR_RULES_HINT))


def stats_error_page(ctx: Ctx, tab: str) -> str:
    return page(ctx, tab, error_block(S.ERR_STATS, [ctx.snap.stats_error]))


# ---------------------------------------------------------------- Подключение (§11.4)

RING_ORDER = ("instagram", "telegram", "youtube", "threads", "pinterest", "tiktok", "facebook",
              "x", "linkedin")
CX, CY, ORBIT, NODE_R, RING_R = 220, 215, 180, 24, 96
STATE_KIND = {S.ST_CONNECTED: "ok", S.ST_LOGIN: "warn", S.ST_TOKEN: "bad", S.ST_NO_KEYS: "bad",
              S.ST_NOT_BUILT: "muted"}


def connection(ctx: Ctx) -> str:
    snap = ctx.snap
    c = M.connection(snap)
    selected = ctx.q("net")
    if selected not in RING_ORDER:
        selected = ""

    def rows(targets):
        out = []
        for t in targets:
            st = c["states"][t.id]
            out.append(f'<li>{disc(t.network)}<span class="mono">{esc(t.id)}</span>'
                       f'<span class="st k-{STATE_KIND[st]}">{esc(st)}</span></li>')
        return "".join(out)

    accounts = (f'<div class="acc"><h3>{esc(S.MAIN_PROFILE)}</h3>'
                f'<ul class="acc-targets">{rows(c["profile"])}</ul></div>')
    if c["others"]:
        accounts += (f'<div class="acc"><h3>{esc(S.OTHER_PAGES)}</h3>'
                     f'<ul class="acc-targets">{rows(c["others"])}</ul></div>')

    nodes, tips = [], []
    for k, net in enumerate(RING_ORDER):
        angle = math.radians(-90 + k * 40)
        x, y = CX + ORBIT * math.cos(angle), CY + ORBIT * math.sin(angle)
        built = net in S.BUILT
        if built:
            t = c["nets"][net]
            state = c["states"][t.id] if t else S.ST_NO_KEYS
        else:
            state = S.ST_NOT_BUILT
        cls = f"node n-{DOMAINS[net]}" + ("" if built else " dim") + (" sel" if net == selected else "")
        nodes.append(
            f'<a class="{cls}" href="/connection?net={net}#net-detail" aria-label="{esc(S.NET_NAME[net])} — '
            f'{esc(state)}"{" aria-current=\"true\"" if net == selected else ""}>'
            f'<circle class="node-disc" cx="{x:.1f}" cy="{y:.1f}" r="{NODE_R}"/>'
            f'<text class="node-mono" x="{x:.1f}" y="{y + 5:.1f}">{esc(S.MONO[net])}</text>'
            f'<text class="node-state k-{STATE_KIND[state]}" x="{x:.1f}" y="{y + NODE_R + 16:.1f}">'
            f'{esc(state)}</text></a>')
        tips.append(f'<text class="tip tip-{DOMAINS[net]}" x="{CX}" y="{CY + 44}" aria-hidden="true">'
                    f'{esc(S.NET_NAME[net])}</text>')
    circ = 2 * math.pi * RING_R
    arc = circ * c["connected"] / 4
    ring = (f'<svg class="ring" viewBox="-20 0 480 440" aria-labelledby="ring-t">'
            f'<title id="ring-t">{esc(S.RING_OF.format(n=c["connected"]))} {esc(S.RING_CAPTION)}</title>'
            f'<circle class="orbit" cx="{CX}" cy="{CY}" r="{ORBIT}"/>'
            f'<circle class="ring-bg" cx="{CX}" cy="{CY}" r="{RING_R}"/>'
            + (f'<circle class="ring-arc" cx="{CX}" cy="{CY}" r="{RING_R}" '
               f'stroke-dasharray="{arc:.1f} {circ:.1f}" transform="rotate(-90 {CX} {CY})"/>'
               if c["connected"] else "") +
            f'<text class="ring-n" x="{CX}" y="{CY + 14}">{c["connected"]}<tspan class="ring-of">'
            f' {esc(S.RING_OF.format(n="").strip())}</tspan></text>'
            f'<text class="cap" x="{CX}" y="{CY + 44}">{esc(S.RING_CAPTION)}</text>'
            f'{"".join(tips)}{"".join(nodes)}</svg>')
    details = _connection_card(ctx, c, selected)
    n = len(c["targets"])
    sub = esc(S.TARGETS_IN_ENV.format(n=n, word=S.plural(n, S.TARGET_WORDS)))
    body = (f'<div class="conn"><section class="accounts" aria-labelledby="acc-h">'
            f'<h2 id="acc-h" class="label">{esc(S.ACCOUNTS)}</h2>{accounts}</section>'
            f'<section class="ring-wrap">{ring}{details}</section></div>')
    return page(ctx, "connection", body, sub=sub)


def _local_time(snap, ts) -> str:
    """A stored UTC stamp as local time in the panel's zone, like every other time on the page."""
    when = M.parse_ts(ts)
    return when.astimezone(snap.zone).strftime("%Y-%m-%d %H:%M") if when else "—"


def _vars_list(names, env) -> str:
    items = []
    for name in names:
        present = bool(env.get(name))
        items.append(f'<li><span class="mono">{esc(name)}</span> '
                     f'<span class="st k-{"ok" if present else "bad"}">'
                     f'{esc(S.VAR_PRESENT if present else S.VAR_MISSING)}</span></li>')
    return f'<ul class="vars">{"".join(items)}</ul>'


def _connection_card(ctx: Ctx, c: dict, net: str) -> str:
    snap = ctx.snap
    env = snap.inputs.env
    if c["empty"] and not net:
        parts = []
        for n in S.BUILT:
            t = c["nets"][n]
            if t:
                parts.append(f'<h3>{disc(n)} {esc(S.NET_NAME[n])}</h3>{_vars_list(t.required_vars, env)}')
        return (f'<div class="card details"><p>{esc(S.EMPTY_CONNECTION)}</p>{"".join(parts)}'
                f'<p class="muted">{esc(S.HOW_TO)}: <span class="mono">{esc(S.HOW_LINKEDIN)}</span> '
                f'(LinkedIn)</p></div>')
    if not net:
        return f'<div class="card details hint"><p class="muted">{esc(S.PICK_NODE)}</p></div>'
    head = f'<h2>{disc(net)} {esc(S.NET_NAME[net])}</h2>'
    if net not in S.BUILT:
        return (f'<div class="card details" id="net-detail">{head}<p><span class="st k-muted">'
                f'{esc(S.ST_NOT_BUILT)}</span> {esc(S.NOT_BUILT_TEXT)}</p></div>')
    blocks = []
    for t in [t for t in c["targets"] if t.network == net]:
        st = c["states"][t.id]
        pub = c["last_pub"].get(t.id)
        if pub:
            when_text = _local_time(snap, pub.get("ts"))
            link = (f' · <a href="{esc(pub["url"])}" target="_blank" rel="noopener">'
                    f'{esc(S.OPEN)}</a>' if pub.get("url") else "")
            pub_html = f'<span class="mono">{esc(when_text)}</span>{link}'
        else:
            pub_html = esc(S.NONE_YET)
        result = c["collect"].get(t.id)
        stats_html = (f'<span class="mono">{esc(_local_time(snap, c["collect_ts"]))}</span> · '
                      f'<span class="core">{esc(S.collect_result(snap.red(result)))}</span>'
                      if result is not None else esc(S.NONE_YET))
        blocks.append(
            f'<div class="tblock"><h3>{target_chip(t.id)} <span class="st k-{STATE_KIND[st]}">'
            f'{esc(st)}</span></h3><p class="label">{esc(S.VARS)}</p>'
            f'{_vars_list(t.required_vars, env)}'
            f'<p><span class="label">{esc(S.LAST_PUBLISH)}:</span> {pub_html}</p>'
            f'<p><span class="label">{esc(S.LAST_STATS)}:</span> {stats_html}</p></div>')
    extra = ""
    if net == "linkedin":
        when, days = M.token_info(snap)
        if when is None:
            token = S.TOKEN_NONE
        elif days is not None and when > snap.now:
            token = S.TOKEN_UNTIL.format(date=S.day_month_year(when.date()), n=days)
        else:
            token = S.TOKEN_EXPIRED.format(date=S.day_month_year(when.date()))
        extra = (f'<p>{esc(token)}</p><p><span class="label">{esc(S.HOW_TO)}:</span> '
                 f'<span class="mono">{esc(S.HOW_LINKEDIN)}</span></p>')
    else:
        extra = f'<p><span class="label">{esc(S.HOW_TO)}:</span> {esc(S.HOW_ENV)}</p>'
    return f'<div class="card details" id="net-detail">{head}{"".join(blocks)}{extra}</div>'


# ---------------------------------------------------------------- Файлы (§11.5)

def _new_folder_card(ctx: Ctx, lane: str, refusal=None) -> str:
    is_open = refusal is not None and refusal.get("lane") == lane
    name = esc(refusal.get("name", "")) if is_open else ""
    return (f'<details class="fcard newcard lane-{lane}" id="new-folder-{lane}"'
            f'{" open" if is_open else ""}>'
            f'<summary><span class="plus">+ {esc(S.LANES[lane])}</span>'
            f'<span class="muted small">{esc(S.NEW_FOLDER)}</span></summary>'
            f'<form method="post" action="/files/new-folder" class="newfolder">'
            f'{hidden(ctx, lane=lane)}'
            f'<label>{esc(S.NEW_FOLDER_NAME)}<input name="name" required maxlength="40" '
            f'pattern="[a-z0-9][a-z0-9\\-]{{0,39}}" value="{name}" autocomplete="off"></label>'
            f'<label>{esc(S.NEW_FOLDER_TITLE)}<input name="title" maxlength="{80}"></label>'
            f'<button class="btn green" type="submit">{esc(S.NEW_FOLDER_SAVE)}</button>'
            f'</form></details>')


def photo_url(folder: str, pid: str, version: str) -> str:
    return "/photo" + qs(folder=folder, id=pid, v=version)


def _folder_card(ctx: Ctx, card) -> str:
    snap = ctx.snap
    lane = card.lane or "none"
    if card.photos:   # a photo folder with uploads shows its first photos (authoring.md §6.7)
        shown = card.photos[:3]
        tiles = "".join(f'<img class="tile" src="{esc(photo_url(card.name, p["id"], "thumb"))}" '
                        f'alt="" loading="lazy" decoding="async">' for p in shown)
        more = len(card.photos) - len(shown)
    else:
        shown = card.entries[:3]
        tiles = "".join(tile(e) for e in shown)
        more = len(card.entries) - len(shown)
    if more > 0:
        tiles += f'<span class="tile tile-more mono">+{S.group(more)}</span>'
    count = (f'<span class="pair"><span class="mono num">{S.group(card.packages)}</span> '
             f'<span class="muted">{esc(S.plural(card.packages, S.PACKAGE_WORDS))}'
             f'{" ·" if card.photos else ""}</span></span>')
    if card.photos:
        count += (f' <span class="pair"><span class="mono num">{S.group(len(card.photos))}</span> '
                  f'<span class="muted">{esc(S.PHOTO_WORD)}</span></span>')
    problems = ""
    if card.invalid:
        problems += f'<p class="red small">{esc(S.FIX_K.format(n=card.invalid))}</p>'
    if card.unapproved:
        problems += f'<p class="red small">{esc(S.UNAPPROVED_K.format(n=card.unapproved))}</p>'
    for p in card.problems:
        problems += f'<p class="red small core">{esc(p)}</p>'
    monos = "".join(disc(M.network_of(t)) for t in card.targets)
    ids = " ".join(card.targets)
    return (f'<article class="fcard lane-{lane}"><h3 class="fcard-title">'
            f'<a href="/files?folder={esc(card.name)}" title="{esc(card.title)}">{esc(card.title)}</a></h3>'
            f'<div class="tiles">{tiles}</div>'
            f'<p class="fcount">{count}</p>'
            f'{problems}{bar(card.fill, "good" if card.readers else "none")}'
            f'<p class="runway{" green" if card.good else ""}">{esc(card.runway)}</p>'
            f'<p class="ftargets" title="{esc(ids)}">{monos}</p></article>')


def files(ctx: Ctx, refusal=None) -> str:
    snap = ctx.snap
    if snap.rules_error:
        return rules_error_page(ctx, "files")
    folder = ctx.q("folder")
    if folder:
        return _folder_view(ctx, folder)
    cards = M.folder_cards(snap)
    n = len(cards)
    sub = esc(S.count(n, S.FOLDER_WORDS))
    sections = []
    if refusal and refusal.get("problems"):
        # the refusal is read on the first screen, above the lanes (the card sits at their end)
        reasons = " ".join(esc(p) for p in refusal["problems"])
        target = f' <a class="btn" href="#new-folder-{esc(refusal.get("lane"))}">{esc(S.TO_FOLDER)}</a>' \
            if refusal.get("lane") in S.LANES else ""
        sections.append(f'<div class="error" role="alert"><p>{esc(S.FOLDER_REFUSED)} '
                        f'<span class="core">{reasons}</span>{target}</p></div>')
    if not cards:
        sections.append(f'<p class="empty">{esc(S.FILES_EMPTY)}</p>')
    for lane in list(S.LANES) + ([None] if any(c.lane is None for c in cards) else []):
        mine = [c for c in cards if c.lane == lane]
        if lane is None:
            title = S.LANE_NONE
        else:
            title = S.LANES[lane]
        packages = sum(c.packages for c in mine)
        meta = (f'· {esc(S.count(len(mine), S.FOLDER_WORDS))} · '
                f'{esc(S.count(packages, S.PACKAGE_WORDS))}')
        body = "".join(_folder_card(ctx, c) for c in mine)
        if lane is not None:
            body += _new_folder_card(ctx, lane, refusal)
        lid = lane or "none"
        sections.append(f'<section class="lane" aria-labelledby="lane-{lid}">'
                        f'<h2 id="lane-{lid}" class="lane-h lane-{lid}"><span>{esc(title)}</span> '
                        f'<span class="muted mono small">{meta}</span></h2>'
                        f'<div class="cards">{body}</div></section>')
    return page(ctx, "files", "".join(sections), sub=sub)


def _folder_view(ctx: Ctx, name: str) -> str:
    snap = ctx.snap
    rows = M.folder_rows(snap, name)
    back = f'<a class="btn" href="/files">{esc(S.ALL_FOLDERS)}</a>'
    if rows is None:
        body = f'{back}<p class="empty">{esc(S.NO_FOLDER.format(name=name))}</p>'
        return page(ctx, "files", body, sub=esc(name))
    folder = snap.inputs.stock.folders[name]
    card = next(c for c in M.folder_cards(snap) if c.name == name)
    out = []
    for r in rows:
        variants = "".join(f'<li>{disc(net)}<span class="vtext" title="{esc(text)}">{esc(text)}</span></li>'
                           for net, text in r["variants"])
        states = "".join(
            f'<li>{target_chip(t)}<span class="st k-{kind}">{esc(text)}'
            + (f' · <a href="{esc(url)}" target="_blank" rel="noopener">{esc(S.OPEN)}</a>' if url else "")
            + "</span></li>" for t, kind, text, url in r["targets"])
        if not r["targets"]:
            label = S.PKG_STATE.get(r["state"], r["state"])
            kind = "bad" if r["state"] in ("invalid", "not-approved", "held", "check-account") else "muted"
            states = f'<li><span class="st k-{kind}">{esc(label)}</span></li>'
        reason = (f'<p class="small"><span class="alert-label">{esc(S.PROBLEM)}</span> '
                  f'<span class="core">{esc(r["reason"])}</span></p>' if r["reason"] else "")
        out.append(f'<article class="pkg">{tile(r["entry"], None, "tile tall")}'
                   f'<div class="pkg-main"><h3 class="mono">{esc(r["file"])}</h3>'
                   f'<p class="muted">{esc(r["theme"])}</p>{reason}</div>'
                   f'<ul class="pkg-variants">{variants}</ul>'
                   f'<ul class="pkg-states">{states}</ul></article>')
    if not rows:
        out.append(f'<p class="empty">{esc(S.FOLDER_NO_PACKAGES)}</p>')
    if not card.readers:
        out.insert(0, f'<p class="muted">{esc(S.NO_TARGETS)}</p>')
    lane = S.LANES.get(folder.lane or "", S.LANE_NONE)
    head = (f'<div class="fview-head">{back}<h2>{esc(card.title)}</h2>'
            f'<span class="muted">{esc(lane)} · {esc(S.count(card.packages, S.PACKAGE_WORDS))}'
            # with no reader the line under it says so; the runway would say it twice
            f'{f" · {esc(card.runway)}" if card.readers else ""}</span></div>')
    sub = esc(S.count(len(rows), S.FILE_WORDS))
    if folder.lane == "photo":
        sub = f"{esc(S.group(len(card.photos)))} {esc(S.PHOTO_WORD)}"
        return page(ctx, "files", head + _photos_section(ctx, name, card.photos)
                    + f'<div class="pkgs">{"".join(out)}</div>', sub=sub,
                    scripts=("author.js",))
    return page(ctx, "files", head + f'<div class="pkgs">{"".join(out)}</div>', sub=sub)


PHOTO_PAGE = 60


def _photos_section(ctx: Ctx, name: str, photos: list) -> str:
    """"Фото" above the package list of a photo-lane folder (authoring.md §6.1, §6.7):
    two upload buttons for author.js, a status line, and a grid of thumbs, newest first, 60
    per step ("показать ещё" links to the next step and works without JS)."""
    snap = ctx.snap
    photos = photos[::-1]   # newest upload first: a fresh upload is on the first screen
    total = len(photos)
    try:
        limit = int(ctx.q("photos") or PHOTO_PAGE)
    except ValueError:
        limit = PHOTO_PAGE
    limit = max(PHOTO_PAGE, min(limit, fphotos.MAX_PHOTOS))
    uses = M.photo_uses(snap, name, ctx.author.drafts.summaries() if ctx.author else ())
    tiles = []
    for i, p in enumerate(photos[:limit]):
        title = snap.red(p["name"])
        use = uses.get(p["id"])
        chip = (f'<span class="st k-{"ok" if use == "published" else "plan"}">'
                f'{esc(S.PHOTO_USE[use])}</span>' if use else "")
        tiles.append(f'<li class="ptile" id="photo-{i + 1}" data-id="{esc(p["id"])}">'
                     f'<img src="{esc(photo_url(name, p["id"], "thumb"))}" alt="{esc(title)}" '
                     f'title="{esc(title)}" loading="lazy" decoding="async">{chip}</li>')
    grid = f'<ul class="pgrid">{"".join(tiles)}</ul>' if tiles else (
        f'<p class="empty">{esc(S.PHOTOS_EMPTY)}</p>')
    more = ""
    if total > limit:
        nxt = min(limit + PHOTO_PAGE, total)
        href = "/files" + qs(folder=name, photos=nxt) + f"#photo-{limit + 1}"
        more = (f'<p class="pmore"><a class="btn" href="{esc(href)}">{esc(S.PHOTOS_MORE)}</a> '
                f'<span class="muted mono">{esc(S.PHOTOS_SHOWN.format(shown=S.group(limit), total=S.group(total)))}'
                f'</span></p>')
    data = esc(json.dumps(S.UPLOAD_JS, ensure_ascii=False))
    accept = ",".join(fphotos.IMAGE_TYPES)
    return (f'<section class="photos" aria-labelledby="photos-h" data-photos="{esc(name)}" '
            f'data-csrf="{esc(ctx.csrf)}" data-strings="{data}">'
            f'<div class="photos-head"><h2 id="photos-h">{esc(S.PHOTOS_H)}</h2>'
            f'<div class="photos-actions">'
            f'<button class="btn" type="button" data-pick="dir" disabled>{esc(S.UPLOAD_DIR)}</button>'
            f'<button class="btn" type="button" data-pick="files" disabled>{esc(S.UPLOAD_FILES)}</button>'
            f'</div>'
            f'<input type="file" data-input="dir" webkitdirectory multiple hidden>'
            f'<input type="file" data-input="files" multiple accept="{esc(accept)}" hidden>'
            f'</div><noscript><p class="muted">{esc(S.PHOTOS_NEED_JS)}</p></noscript>'
            f'<p class="upload-status" role="status" aria-live="polite"></p>'
            f'<ul class="upload-skipped"></ul>'
            f'{grid}{more}</section>')


# ---------------------------------------------------------------- Правила (§11.6)

HOURS = tuple(f"{h:02d}:00" for h in range(6, 24))


def rules(ctx: Ctx, refusal=None) -> str:
    snap = ctx.snap
    if snap.rules_error:
        return rules_error_page(ctx, "rules")
    rs = snap.inputs.ruleset
    net = ctx.q("net")
    counts: dict = {}
    running: set = set()
    for r in rs.rules:
        for n in r.networks():
            counts[n] = counts.get(n, 0) + 1
            if r.active:
                running.add(n)
    chip_html = []
    for key, label, n in [("", S.ALL, len(rs.rules))] + [
            (k, S.MONO[k], counts[k]) for k in S.BUILT if counts.get(k)]:
        dot = '<span class="dot" aria-hidden="true"></span>' if key in running else ""
        run = f'<span class="sr"> · {esc(S.RULES_RUNNING[2])}</span>' if key in running else ""
        icon = disc(key) if key else esc(label)
        chip_html.append(f'<a class="chip{" on" if key == net else ""}" href="/rules{qs(net=key)}"'
                         f'{" aria-current=\"true\"" if key == net else ""}>{icon}'
                         f'<span class="mono n">{n}</span>{dot}{run}</a>')
    sub_right = f'<nav class="chips" aria-label="Сети">{"".join(chip_html)}</nav>'
    shown = [r for r in rs.rules if not net or net in r.networks()]
    banner = ""
    if refusal and refusal.get("stale"):
        banner = (f'<div class="error" role="alert"><p>{esc(S.STALE)} '
                  f'<a class="btn" href="/rules">{esc(S.RELOAD)}</a></p></div>')
    elif refusal and refusal.get("problems"):
        rid = refusal.get("rule") or "new"
        text = (S.NEW_REFUSED if rid == "new" else S.RULE_REFUSED.format(id=rid))
        banner = (f'<div class="error" role="alert"><p>{esc(text)} '
                  f'<a class="btn" href="#rule-{esc(rid)}">{esc(S.TO_RULE)}</a></p></div>')
    head = "".join(f'<div class="hc c-{k}">{esc(t)}</div>' for k, t in (
        ("start", S.COL_START), ("account", S.COL_ACCOUNT), ("source", S.COL_SOURCE),
        ("target", S.COL_TARGET), ("days", S.COL_DAYS), ("hours", S.COL_HOURS),
        ("tz", S.COL_TZ)))
    rows = "".join(_rule_row(ctx, r, refusal) for r in shown)
    if rs.rules:
        table = (f'<div class="rtable" role="list"><div class="rrow rhead" aria-hidden="true">{head}</div>'
                 f'{rows}</div>')
    else:
        table = f'<p class="empty">{esc(S.RULES_EMPTY)}</p>'
    body = banner + table + _new_rule_form(ctx, refusal)
    body += '<datalist id="zones">' + "".join(
        f'<option value="{esc(z)}">' for z in M.zones()) + "</datalist>"
    return page(ctx, "rules", body, sub=esc(S.count(len(rs.rules), ("правило", "правила", "правил"))),
                sub_right=sub_right)


def _cell(key: str, label: str, inner: str) -> str:
    return f'<div class="rc c-{key}"><span class="cell-label">{esc(label)}</span>{inner}</div>'


def _rule_row(ctx: Ctx, rule, refusal) -> str:
    snap = ctx.snap
    rev = snap.inputs.ruleset.revision
    base = dict(rev=rev, rule=rule.id)
    # Пуск
    if rule.active:
        since = M.parse_ts(rule.active_since or "")
        when = S.day_month(since.astimezone(snap.zone).date()) if since else "—"
        state = f'<span class="start-state green">{esc(S.RUNNING_SINCE.format(date=when))}</span>'
        btn = (f'<form method="post" action="/rules/stop">{hidden(ctx, **base)}'
               f'<button class="round stop" type="submit" aria-label="{esc(S.STOP.format(id=rule.id))}">'
               f'<span aria-hidden="true">■</span></button></form>')
    else:
        state = f'<span class="start-state muted">{esc(S.DRAFT)}</span>'
        btn = (f'<form method="post" action="/rules/start">{hidden(ctx, **base)}'
               f'<button class="round play" type="submit" aria-label="{esc(S.START.format(id=rule.id))}">'
               f'<span aria-hidden="true">▶</span></button></form>')
    start = _cell("start", S.COL_START, f'<div class="start">{btn}{state}</div>')
    # Аккаунт
    profile = M.profile_targets()
    label = S.MAIN_PROFILE if any(t in profile for t in rule.targets) else S.OTHER_PAGES
    monos = "".join(disc(M.network_of(t)) for t in rule.targets)
    account = _cell("account", S.COL_ACCOUNT,
                    f'<p class="strong">{esc(label)}</p><p class="monos">{monos}</p>')
    # Откуда
    folder = snap.inputs.stock.folders.get(rule.folder)
    runway, fill, good = M.rule_runway(snap, rule)
    lane = folder.lane if folder else None
    title = snap.red(folder.title if folder else rule.folder)
    n = M.folder_count(snap, rule.folder)
    source = _cell("source", S.COL_SOURCE,
                   f'<div class="mini lane-{lane or "none"}"><div class="mini-top">'
                   f'<a class="mini-title" href="/files?folder={esc(rule.folder)}" title="{esc(title)}">'
                   f'{esc(title)}</a><span class="mini-count"><span class="mono num-s">{S.group(n)}</span>'
                   f'<span class="muted small">{esc(S.plural(n, S.PACKAGE_WORDS))}</span></span></div>'
                   f'<p class="small"><span class="lchip lane-{lane or "none"}">'
                   f'{esc(S.LANES.get(lane or "", S.LANE_NONE))}</span></p>'
                   f'{bar(fill, "good")}<p class="mono small{" green" if good else ""}">'
                   f'{esc(runway)}</p></div>')
    # Куда
    fmt = S.FORMAT_PHOTO if lane == "photo" else S.FORMAT_TEXT
    target = _cell("target", S.COL_TARGET,
                   f'<p class="strong">{esc(fmt)}</p><ul class="tlist">'
                   + "".join(f"<li>{target_chip(t)}</li>" for t in rule.targets) + "</ul>")
    # Дни
    day_btns = "".join(
        f'<button class="tog day{" on" if d in rule.days else ""}" type="submit" name="day" '
        f'value="{d}" aria-pressed="{"true" if d in rule.days else "false"}">{esc(S.DAYS_SHORT[k])}</button>'
        for k, d in enumerate(fruleset.DAYS))
    nd = len(rule.days)
    select_all = ("" if nd == 7 else
                  f' · <button class="linkbtn" type="submit" name="day" value="all">{esc(S.SELECT_ALL)}</button>')
    days = _cell("days", S.COL_DAYS,
                 f'<form method="post" action="/rules/day" class="days-form">{hidden(ctx, **base)}'
                 f'<div class="days" role="group" aria-label="{esc(S.COL_DAYS)}">{day_btns}</div>'
                 f'<p class="small muted">{esc(S.DAYS_A_WEEK.format(n=nd, word=S.plural(nd, S.DAY_WORDS)))}'
                 f'{select_all}</p></form>')
    # Время
    hour_btns = "".join(
        f'<button class="tog hour mono{" on" if h in rule.hours else ""}" type="submit" name="hour" '
        f'value="{h}" aria-pressed="{"true" if h in rule.hours else "false"}">{h}</button>'
        for h in HOURS)
    nh = len(rule.hours)
    hints = "".join(
        f'<li title="{esc(S.LIMIT_BASIS[n])}">{esc(S.LIMIT_HINT.format(net=S.MONO[n], n=snap.inputs.ruleset.limit(n).max_per_day, gap=f"{snap.inputs.ruleset.limit(n).min_gap_hours:g}"))}</li>'
        for n in sorted(rule.networks(), key=lambda n: config.NETWORK_ORDER[n]))
    hints += f'<li>{esc(S.LIMIT_NOTE_X if "x" in rule.networks() else S.LIMIT_NOTE)}</li>'
    hours = _cell("hours", S.COL_HOURS,
                  f'<form method="post" action="/rules/hour">{hidden(ctx, **base)}'
                  f'<div class="hours" role="group" aria-label="{esc(S.COL_HOURS)}">{hour_btns}</div></form>'
                  f'<p class="small muted">{esc(S.TIMES_A_DAY.format(n=nh, word=S.plural(nh, S.TIMES_WORDS), w=nh * nd))}</p>'
                  f'<ul class="hints small muted">{hints}</ul>')
    # Пояс
    tz = _cell("tz", S.COL_TZ,
               f'<form method="post" action="/rules/zone" class="zone-form">{hidden(ctx, **base)}'
               f'<input name="zone" list="zones" value="{esc(rule.timezone)}" '
               f'aria-label="{esc(S.ZONE_LABEL.format(id=rule.id))}" maxlength="64" autocomplete="off">'
               f'<span class="zone-row"><span class="small muted mono">'
               f'{esc(M.zone_offset(rule.timezone, snap.now))}</span>'
               f'<button class="btn" type="submit">{esc(S.ZONE_SAVE)}</button></span></form>')
    # under the row
    problems = list(snap.rule_problems.get(rule.id, []))
    if refusal and refusal.get("rule") == rule.id and refusal.get("problems"):
        problems = refusal["problems"]
    stale = (f'<p class="red" role="alert">{esc(S.STALE)}</p>'
             if refusal and refusal.get("stale") and refusal.get("rule") == rule.id else "")
    cost = M.rule_x_week(snap, rule)
    foot = alert(S.PROBLEM, problems) + stale
    if cost is not None:
        foot += f'<p class="small muted mono">{esc(S.X_WEEK.format(cost=f"{cost:.2f}"))}</p>'
    foot_html = f'<div class="rfoot">{foot}</div>' if foot else ""
    return (f'<div class="rrow{" active" if rule.active else ""}" id="rule-{esc(rule.id)}" role="listitem">'
            f'<h2 class="sr">{esc(rule.id)}</h2>'
            f'{start}{account}{source}{target}{days}{hours}{tz}{foot_html}</div>')


def _new_rule_form(ctx: Ctx, refusal) -> str:
    snap = ctx.snap
    rs = snap.inputs.ruleset
    is_new = bool(refusal and refusal.get("rule") == "new")
    is_open = is_new or not rs.rules
    form = refusal.get("form", {}) if is_new else {}

    def picked(name, value, default):
        values = form.get(name) if is_new else None
        return value in (values if values is not None else default)

    folders = "".join(
        f'<option value="{esc(n)}"{" selected" if (form.get("folder") or [""])[0] == n else ""}>'
        f'{esc(snap.red(f.title or n))} ({esc(n)})</option>'
        for n, f in sorted(snap.inputs.stock.folders.items()))
    targets = "".join(
        f'<label class="check"><input type="checkbox" name="targets" value="{esc(t.id)}"'
        f'{" checked" if picked("targets", t.id, M.profile_targets()) else ""}>{target_chip(t.id)}</label>'
        for t in config.derived_targets(snap.inputs.env))
    days = "".join(
        f'<label class="check"><input type="checkbox" name="days" value="{d}"'
        f'{" checked" if picked("days", d, ("mon", "wed", "fri")) else ""}>{esc(S.DAYS_SHORT[k])}</label>'
        for k, d in enumerate(fruleset.DAYS))
    hours = "".join(
        f'<label class="check mono"><input type="checkbox" name="hours" value="{h}"'
        f'{" checked" if picked("hours", h, ("10:00",)) else ""}>{h}</label>' for h in HOURS)
    problems = alert(S.PROBLEM, refusal.get("problems", [])) if is_new else ""
    rid = esc((form.get("id") or [""])[0])
    zone = esc((form.get("zone") or [snap.machine_tz])[0])
    return (f'<details class="newrule"{" open" if is_open else ""} id="rule-new">'
            f'<summary class="btn">{esc(S.NEW_RULE)}</summary>'
            f'<form method="post" action="/rules/new" class="newrule-form">{hidden(ctx, rev=rs.revision)}'
            f'<label>{esc(S.NEW_RULE_ID)}<input name="id" required maxlength="40" value="{rid}" '
            f'autocomplete="off"></label>'
            f'<label>{esc(S.NEW_RULE_FOLDER)}<select name="folder" required>{folders}</select></label>'
            + ("" if folders else f'<p class="muted">{esc(S.NO_FOLDERS_YET)} '
                                  f'<a class="btn" href="/files">{esc(dict(S.TABS)["files"])}</a></p>') +
            f'<fieldset><legend>{esc(S.NEW_RULE_TARGETS)}</legend>{targets}</fieldset>'
            f'<fieldset><legend>{esc(S.COL_DAYS)}</legend>{days}</fieldset>'
            f'<fieldset class="hours-set"><legend>{esc(S.COL_HOURS)}</legend>{hours}</fieldset>'
            f'<label>{esc(S.COL_TZ)}<input name="zone" list="zones" value="{zone}" maxlength="64" '
            f'autocomplete="off"></label>{problems}'
            f'<button class="btn green" type="submit">{esc(S.NEW_RULE_SAVE)}</button></form></details>')


# ---------------------------------------------------------------- Календарь (§11.7)

def calendar(ctx: Ctx) -> str:
    snap = ctx.snap
    if snap.rules_error:
        return rules_error_page(ctx, "calendar")
    net = ctx.q("net")
    if net not in S.BUILT:
        net = ""
    try:
        more = max(0, min(int(ctx.q("more", "0")), M.MAX_MORE))
    except ValueError:
        more = 0
    plan = snap.plan_for(more)
    by_day = M.day_rows(snap, plan)
    months = M.calendar_months(snap, more)
    first = _dt.date(months[0][0], months[0][1], 1)
    last_y, last_m = months[-1]
    last = _dt.date(last_y, last_m, _calendar.monthrange(last_y, last_m)[1])
    counts: dict = {}
    total = 0
    for d, rows in by_day.items():
        if first <= d <= last:
            for r in rows:
                if r.counted:
                    counts[r.network] = counts.get(r.network, 0) + 1
                    total += 1
    today = snap.today
    # header stats (no X here: the X spend lives in the top bar, §14)
    p = snap.plan
    pubs = p.publications_7d
    stat1 = (f'<div class="stat"><span class="mono big">{S.group(pubs)}</span>'
             f'<span class="muted small">{esc(S.plural(pubs, S.PUBS_WEEK))}</span></div>')
    running = f"{p.active} {S.plural(p.active, S.RULES_RUNNING)}"
    drafts = f" · {S.DRAFTS_MORE.format(n=p.drafts)}" if p.drafts else ""
    stat2 = (f'<div class="stat"><span class="mono big">{p.active}</span>'
             f'<span class="muted small">{esc(running[len(str(p.active)) + 1:])}{esc(drafts)}</span></div>')
    first_out = p.first_runout()
    if not p.active:
        stat3 = f'<div class="stat"><span class="big">{esc(S.RUNOUT_NONE)}</span></div>'
    elif first_out is None:
        stat3 = (f'<div class="stat"><span class="mono big green">{esc(S.RUNOUT_LONG)}</span>'
                 f'<span class="muted small">{esc(S.RUNOUT_LONG_LABEL)}</span></div>')
    else:
        d = first_out[0].astimezone(snap.zone).date()
        stat3 = (f'<div class="stat"><span class="mono big red">{esc(S.day_month_year(d))}</span>'
                 f'<span class="muted small">{esc(S.RUNOUT_LABEL.format(rule=first_out[1]))}</span></div>')
    head = (f'<div class="cal-head"><a class="btn" href="#today">{esc(S.TODAY)}</a>'
            f'<h2>{esc(S.month_title(today.year, today.month))}</h2>'
            f'<div class="stats">{stat1}{stat2}{stat3}</div></div>')
    chip_html = chips(ctx, counts, total, net, "/calendar", {"more": more or None})
    month_html = "".join(_month(ctx, y, m, by_day, net, more) for y, m in months)
    more_link = ""
    if more < M.MAX_MORE:
        more_link = (f'<p class="more"><a class="btn" href="/calendar{qs(net=net, more=more + 1)}">'
                     f'{esc(S.MORE_MONTHS)}</a></p>')
    dialog = ""
    day = ctx.q("day")
    if day:
        try:
            dialog = _day_dialog(ctx, _dt.date.fromisoformat(day), by_day, net, more)
        except ValueError:
            dialog = ""
    body = dialog + head + chip_html + month_html + more_link
    return page(ctx, "calendar", body)


def _month(ctx: Ctx, year: int, month: int, by_day: dict, net: str, more: int) -> str:
    snap = ctx.snap
    today = snap.today
    n_days = _calendar.monthrange(year, month)[1]
    lead = _dt.date(year, month, 1).weekday()
    cells = ['<div class="cell blank" aria-hidden="true"></div>'] * lead
    month_total = 0
    for day in range(1, n_days + 1):
        d = _dt.date(year, month, day)
        listed = [r for r in by_day.get(d, []) if not net or r.network == net]
        rows = [r for r in listed if r.counted]
        month_total += len(rows)
        cls = "cell" + (" past" if d < today else "") + (" today" if d == today else "")
        today_word = f'<span class="today-word">{esc(S.TODAY)}</span>' if d == today else ""
        anchor = ' id="today"' if d == today else ""
        if not listed:
            cells.append(f'<div class="{cls}"{anchor}><span class="dnum mono">{day}</span>'
                         f'{today_word}</div>')
            continue
        per: dict = {}
        for r in rows:
            per[r.network] = per.get(r.network, 0) + 1
        nets = sorted(per, key=lambda n: (-per[n], config.NETWORK_ORDER.get(n, 9)))
        chips_html = "".join(f'<span class="cchip">{disc(n)}<span class="mono">{per[n]}</span></span>'
                             for n in nets[:4])
        if len(nets) > 4:
            chips_html += f'<span class="cchip mono">+{len(nets) - 4}</span>'
        words = S.count(len(rows), S.PUB_WORDS)
        href = "/calendar" + qs(day=d.isoformat(), net=net, more=more or None)
        label = f"{S.day_month(d)}: {words}" + (f" · {S.TODAY}" if d == today else "")
        cells.append(f'<a class="{cls}"{anchor} href="{esc(href)}" aria-label="{esc(label)}">'
                     f'<span class="dnum mono">{day}</span>'
                     f'<span class="dtotal mono">{len(rows) if rows else ""}</span>'
                     f'<span class="cchips">{chips_html}</span>{today_word}</a>')
    weekdays = "".join(f'<div class="wd">{esc(w)}</div>' for w in S.DAYS_SHORT)
    return (f'<section class="month" id="m-{year}-{month:02d}" aria-labelledby="mh-{year}-{month}">'
            f'<h3 id="mh-{year}-{month}"><span>{esc(S.MONTHS_NOM[month - 1])}</span> '
            f'<span class="muted mono">{year}</span>'
            f'<span class="muted small mtotal">{esc(S.count(month_total, S.PUB_WORDS))}</span></h3>'
            f'<div class="grid" aria-hidden="false"><div class="wds" aria-hidden="true">{weekdays}</div>'
            f'{"".join(cells)}</div></section>')


def _day_dialog(ctx: Ctx, d: _dt.date, by_day: dict, net: str, more: int) -> str:
    snap = ctx.snap
    rows = [r for r in by_day.get(d, []) if not net or r.network == net]
    real = [r for r in rows if r.counted]
    title = f"{S.day_month(d)} · {S.DAYS_LOWER[d.weekday()]}"
    if d == snap.today:
        title += f" · {S.TODAY}"
    items = []
    for r in rows:
        link = (f' · <a href="{esc(r.url)}" target="_blank" rel="noopener">{esc(S.OPEN)}</a>'
                if r.url else "")
        state_cls = "tag" if r.draft else f"k-{r.kind}"
        items.append(f'<li class="drow"><span class="dtime mono">{esc(r.time)}</span>'
                     f'{tile(r.entry, r.network, "tile sm") if r.entry else "<span class=\"tile sm tile-text\" aria-hidden=\"true\"></span>"}'
                     f'<span class="dtarget">{target_chip(r.target)}</span>'
                     f'<span class="dstate {state_cls}">{esc(r.state)}{link}</span></li>')
    if not items:
        items.append(f'<li class="drow empty">{esc(S.DAY_EMPTY)}</li>')
    close = "/calendar" + qs(net=net, more=more or None)
    return (f'<dialog class="day" id="day" open aria-labelledby="day-h">'
            f'<div class="day-head"><h2 id="day-h">{esc(title)}</h2>'
            f'<span class="muted mono">{esc(S.count(len(real), S.PUB_WORDS))}</span>'
            f'<a class="btn close" href="{esc(close)}" data-close="day">✕ {esc(S.CLOSE)}</a></div>'
            f'<ol class="drows">{"".join(items)}</ol></dialog>')


# ---------------------------------------------------------------- Охваты (§11.8)

def reach(ctx: Ctx) -> str:
    snap = ctx.snap
    if snap.stats_error:
        return stats_error_page(ctx, "reach")
    sort = ctx.q("sort", "popular")
    if sort not in dict(S.SORTS):
        sort = "popular"
    net = ctx.q("net")
    if net not in S.BUILT:
        net = ""
    all_rows = M.reach_rows(snap)
    sorts = "".join(
        f'<a class="sbtn{" on" if key == sort else ""}" href="/reach{qs(sort=key, net=net)}"'
        f'{" aria-current=\"true\"" if key == sort else ""}>{esc(label)}</a>' for key, label in S.SORTS)
    sorts_html = f'<nav class="sorts" aria-label="Сортировка">{sorts}</nav>'
    if snap.latest is None:
        block = (f'<p class="empty">{esc(S.REACH_NEVER)} <span class="mono">{esc(S.STATS_COMMAND)}</span></p>'
                 if all_rows else f'<p class="empty">{esc(S.REACH_NO_POSTS)}</p>')
        return page(ctx, "reach", block, sub=esc(S.count(len(all_rows), S.PUB_WORDS)))
    if not all_rows:
        return page(ctx, "reach", f'<p class="empty">{esc(S.REACH_NO_POSTS)}</p>',
                    sub=esc(S.count(0, S.PUB_WORDS)))
    counts: dict = {}
    for r in all_rows:
        counts[r.network] = counts.get(r.network, 0) + 1
    rows = M.sort_reach([r for r in all_rows if not net or r.network == net], sort)
    totals = [S.count(len(rows), S.PUB_WORDS)]
    for key in ("views", "likes", "comments"):
        values = [r.metrics[key] for r in rows if key in r.metrics]
        if values:
            s = sum(values)
            totals.append(f"{S.abbrev(s)} {S.plural(s if s < 1000 else 5, S.TOTALS_WORDS[key])}")
    sub = " · ".join(esc(t) for t in totals)
    notes = "".join(f'<li>{target_chip(t)} <span class="st k-warn">'
                    f'{esc(S.NO_ACCESS.format(perm=perm))}</span></li>' for t, perm in M.no_access(snap))
    notes_html = f'<ul class="notes">{notes}</ul>' if notes else ""
    items = []
    for r in rows:
        when = r.when.astimezone(snap.zone).date().isoformat() if r.when else "—"
        link = (f' · <a href="{esc(r.url)}" target="_blank" rel="noopener">{esc(S.OPEN)}</a>'
                if r.url else "")
        metrics = "".join(
            f'<div class="m m-{key}"><span class="mono mv">'
            f'{esc(S.abbrev(r.metrics[key]) if key in r.metrics else S.NO_METRIC)}</span>'
            f'<span class="ml">{esc(label)}</span></div>' for key, label in S.METRICS)
        items.append(f'<li class="post">{tile(r.entry, r.network, "tile")}'
                     f'<div class="ptext"><p class="clamp" title="{esc(r.text)}">{esc(r.text)}</p>'
                     f'<p class="meta mono small">{disc(r.network)} {esc(when)} · {esc(r.target)}{link}</p></div>'
                     f'<div class="metrics">{metrics}</div></li>')
    body = (chips(ctx, counts, len(all_rows), net, "/reach", {"sort": sort}) + notes_html
            + f'<ol class="posts">{"".join(items)}</ol>')
    return page(ctx, "reach", body, sub=sub, sub_right=sorts_html)


# ---------------------------------------------------------------- Подписчики (§11.9)

def _sparkline(points: list, down: bool) -> str:
    values = [n for _, n in points]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    w, h = 300, 64
    coords = []
    for k, v in enumerate(values):
        x = k * w / (len(values) - 1)
        y = 4 + (1 - (v - lo) / span) * (h - 8)
        coords.append(f"{x:.1f},{y:.1f}")
    line = "M" + " L".join(coords)
    area = f"{line} L{w},{h} L0,{h} Z"
    cls = "down" if down else "up"
    return (f'<svg class="spark {cls}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<path class="area" d="{area}"/><path class="line" d="{line}"/></svg>')


def followers(ctx: Ctx) -> str:
    snap = ctx.snap
    if snap.stats_error:
        return stats_error_page(ctx, "followers")
    period = ctx.q("period", "30")
    if period not in M.PERIOD_DAYS:
        period = "30"
    periods = "".join(
        f'<a class="sbtn{" on" if key == period else ""}" href="/followers{qs(period=key)}"'
        f'{" aria-current=\"true\"" if key == period else ""}>{esc(label)}</a>' for key, label in S.PERIODS)
    periods_html = f'<nav class="sorts" aria-label="Период">{periods}</nav>'
    cards = M.follower_cards(snap, period)
    out = []
    for c in cards:
        if c.delta is None:
            delta_html = ""
            spark = f'<p class="spark-none muted">{esc(S.FEW_POINTS)}</p>'
        else:
            kind = "green" if c.delta > 0 else ("red" if c.delta < 0 else "muted")
            delta_html = f'<span class="delta mono {kind}">{esc(S.signed(c.delta))}</span>'
            spark = _sparkline(c.points, c.delta < 0)
        out.append(f'<article class="card fol"><h2>{target_chip(c.target)}</h2>'
                   f'<p><span class="mono fnum">{S.group(c.number)}</span> {delta_html}</p>{spark}'
                   f'<p class="small muted mono">{esc(S.FOR_DAYS.format(n=c.days, word=S.plural(c.days, S.DAY_WORDS)))}</p>'
                   f'</article>')
    x_mode = (snap.inputs.env.get("X_STATS") or "off").strip()
    special = [("linkedin", "linkedin", S.LINKEDIN_CARD)]
    if not any(c.network == "x" for c in cards):
        special.append(("x", "x", S.X_ON_CARD if x_mode == "weekly" else S.X_OFF_CARD))
    for net, target, text in special:
        out.append(f'<article class="card fol special"><h2>{disc(net)} {esc(S.NET_NAME[net])}</h2>'
                   f'<p class="muted">{esc(text)}</p></article>')
    total = sum(c.number for c in cards)
    sub = (f'<span class="mono">{esc(S.group(total))}</span> {esc(S.plural(total, S.FOLLOWER_WORDS))} · '
           f'<span class="mono">{len(cards)}</span> {esc(S.plural(len(cards), S.ACCOUNT_WORDS))}')
    empty = ""
    if snap.latest is None:
        empty = (f'<p class="empty">{esc(S.REACH_NEVER)} <span class="mono">{esc(S.STATS_COMMAND)}</span></p>')
    body = empty + f'<div class="fols">{"".join(out)}</div>'
    return page(ctx, "followers", body, sub=sub, sub_right=periods_html)


# ---------------------------------------------------------------- Диалоги (§11.10)

def dialogs(ctx: Ctx) -> str:
    reasons = "".join(f"<li>{esc(r)}</li>" for r in S.DIALOGS_REASONS)
    body = (f'<section class="card dialogs"><h2>{esc(S.DIALOGS_TITLE)}</h2><ul>{reasons}</ul>'
            f'<p class="muted">{esc(S.DIALOGS_TRIGGER)}</p></section>')
    return page(ctx, "dialogs", body, title=S.DIALOGS_OFF)


# ---------------------------------------------------------------- Создать (authoring.md §8)

def _author_state(ctx):
    from factory.authoring import budget, profile
    a = ctx.author
    env = a.ai.env()
    why = {}
    for op in ("topics", "expand", "regenerate", "voice"):
        why[op] = a.ai.availability(op, env)
    bounds = {op: f"до ${budget.button(op, a.clock()):.2f}" for op in why}
    try:
        month = a.ai_ledger.display(env)
        limited = a.ai_ledger.month_total() + max(budget.button(op, a.clock()) for op in why) > budget.cap(env)
    except budget.Refusal as exc:
        month, limited = exc.message, True
    month_html = (f'<span id="ai-month" class="mono small{" k-bad" if limited else ""}" '
                  f'title="Gemini за {esc(budget.MONTHS[a.ai_ledger.now().month - 1])}, по UTC">'
                  f'{esc(month)}{" · лимит" if limited else ""}</span>')
    author = profile.load(a.paths.content)
    return why, bounds, month_html, author


def _create_data(ctx, why, bounds, **extra):
    from factory.authoring import gemini
    values = dict(strings=S.CREATE_JS, upload_strings=S.UPLOAD_JS, networks=S.CREATE_NETWORKS,
                  why=why, bounds=bounds, csrf=ctx.csrf, **extra)
    return esc(json.dumps(values, ensure_ascii=False))


def _create_notice(why, main="expand"):
    # One visible reason per state, worded for the screen's main action (the start page spends
    # on topics, a draft on «Развернуть»). Each spending control also carries its own title.
    reasons = list(dict.fromkeys(v for v in why.values() if v))
    if reasons and all(r.startswith("Бюджет ИИ") for r in reasons):
        reasons = [why[main] or reasons[0]]
    return "".join(f'<p class="create-notice k-bad" role="alert">{esc(v)}</p>' for v in reasons)


def _stamp(iso):
    """«11 нояб., 09:40» (UTC, like the draft page)."""
    date = config.parse_utc(iso)
    return f"{S.day_short(date)}, {date:%H:%M}"


def create(ctx: Ctx) -> str:
    from factory.authoring import profile
    why, bounds, month, author = _author_state(ctx)
    cards = M.folder_cards(ctx.snap) if ctx.snap.inputs is not None else []
    recent = []
    for card in cards:
        if card.lane == "photo":
            recent.extend(dict(p, folder=card.name) for p in card.photos)
    recent.sort(key=lambda p: (p["ts"], p["id"]), reverse=True)
    recent_html = ""
    if recent:
        buttons = "".join(
            f'<button class="recent-photo" type="button" data-recent="{esc(p["id"])}" '
            f'data-folder="{esc(p["folder"])}" aria-label="Пост из фото {esc(p["name"])}">'
            f'<img src="{esc(photo_url(p["folder"], p["id"], "thumb"))}" alt="{esc(p["name"])}"></button>'
            for p in recent[:8])
        recent_html = (f'<section><h2>Недавние фото</h2><p class="recent-hint muted small">{esc(S.CREATE_RECENT_HINT)}</p>'
                       f'<div class="recent-photos">{buttons}</div></section>')
    summaries = ctx.author.drafts.summaries()
    drafts_html = ""
    if summaries:
        rows = "".join(
            f'<li><a class="draft-row" href="/create/{esc(d["id"])}">'
            f'<img src="{esc(photo_url(d["folder"], d["photo"], "thumb"))}" alt="">'
            f'<span class="draft-topic" title="{esc(d["topic"] or "без темы")}">{esc(d["topic"] or "без темы")}</span>'
            f'<span class="draft-meta small"><span class="draft-stage k-{"bad" if d["stage"] in ("error", "over") else "muted"}">'
            f'{esc(S.DRAFT_STAGE[d["stage"]])}</span><span class="muted mono">{esc(_stamp(d["updated"]))}</span></span></a></li>'
            for d in summaries[:10])
        drafts_html = f'<section><h2>Черновики · {len(summaries)}</h2><ul class="draft-list">{rows}</ul></section>'
    # Without a key (or past the cap) the zone promises no topics.
    hint_topics = "" if why["topics"] else (
        f' · Gemini предложит темы (<span class="nowrap">{esc(bounds["topics"])}</span>)')
    profile_label = S.CREATE_PROFILE_FILLED if any(profile.value(author, n) for n, *_ in profile.FIELDS) else S.CREATE_PROFILE_EMPTY
    body = (f'<div class="create-start" data-create="{_create_data(ctx, why, bounds)}">'
            f'{_create_notice(why, "topics")}<label class="create-drop" id="create-drop">'
            f'<strong>{esc(S.CREATE_DROP)}</strong><span class="btn">{esc(S.CREATE_PICK)}</span>'
            f'<span class="small muted drop-hint">{esc(S.CREATE_FORMATS)}{hint_topics}</span>'
            f'<input id="create-file" type="file" accept="image/jpeg,image/png,image/webp" class="create-file">'
            f'</label><p class="create-status" role="status" aria-live="polite"></p>'
            f'<p class="profile-line"><a href="/create/profile">{esc(profile_label)}</a></p>'
            f'<noscript><p>{esc(S.CREATE_NEED_JS)}</p></noscript>{recent_html}{drafts_html}</div>')
    return page(ctx, "create", body, sub="Новый пост", sub_right=month,
                scripts=("author.js", "create.js"))


def _spend_button(op, label, why, cls="btn", **attrs):
    extra = " ".join(f'{k.replace("_", "-")}="{esc(v)}"' for k, v in attrs.items())
    disabled = ' disabled' if why else ""
    title = f' title="{esc(why)}"' if why else ""
    return f'<button class="{cls}" type="button" data-op="{op}"{disabled}{title} {extra}>{esc(label)}</button>'


def _text_check(network, value):
    from factory.authoring import gemini
    shown = gemini.present(network, value["text"])
    line = f'<p class="mono small">{esc(shown["line"])}</p>' if shown["line"] else ""
    problems = ""
    if shown["problems"]:
        problems = '<div class="k-bad text-errors" role="alert">' + "".join(
            f'<p>{esc(p)}</p>' for p in shown["problems"]) + '</div>'
    return line + problems


def _text_card(network, value, why, bounds):
    n = esc(network)
    return (f'<article class="create-text" data-network="{n}"><h3>{esc(S.CREATE_NETWORKS[network])}</h3>'
            f'<label class="sr" for="text-{n}">Текст {esc(S.CREATE_NETWORKS[network])}</label>'
            f'<textarea id="text-{n}" class="text-editor" rows="5">{esc(value["text"])}</textarea>'
            f'<div class="text-check">{_text_check(network, value)}</div>'
            f'<p class="save-status small" role="status"></p>'
            f'<div class="regenerate-row"><input aria-label="Пожелание для {esc(S.CREATE_NETWORKS[network])}" '
            f'placeholder="{esc(S.CREATE_JS["wish"])}" maxlength="200" class="wish">'
            f'{_spend_button("regenerate", S.CREATE_JS["regenerate"] + " · " + bounds["regenerate"], why["regenerate"])}</div></article>')


def create_draft(ctx: Ctx) -> str:
    why, bounds, month, author = _author_state(ctx)
    draft = ctx.author.drafts.load(ctx.path[len("/create/"):])
    data = _create_data(ctx, why, bounds, draft=draft)
    topics = []
    for item in draft["topics"]:
        topic = item["title"] + " — " + item["angle"]
        chosen = draft["topic"] == topic
        topics.append(f'<button class="topic-card" type="button" aria-pressed="{str(chosen).lower()}" '
                      f'data-topic="{esc(topic)}"><strong>{esc(item["title"])}</strong>'
                      f'<span>{esc(item["angle"])}</span><span class="chosen">{"выбрано" if chosen else ""}</span></button>')
    topic_button = S.CREATE_JS["more_topics"] if topics else S.CREATE_JS["topics"]
    expand = S.CREATE_JS["expand_again"] if any(v["source"] == "edited" for v in draft["variants"].values()) else S.CREATE_JS["expand"]
    error = draft["error"]
    error_html = (f'<div class="create-error k-bad" role="alert"><p>{esc(error["text"])}</p>'
                  f'<button class="btn" type="button" data-retry="{esc(error["op"])}" '
                  f'data-network="{esc(error.get("network", ""))}">'
                  f'{esc(S.CREATE_JS["repeat"] + " · " + bounds[error["op"]])}</button></div>'
                  if error else '<div class="create-error" hidden></div>')
    # A failed topics request is retried by the banner's button, not by a second one.
    topics_hidden = {"hidden": ""} if error and error["op"] == "topics" else {}
    texts = "".join(_text_card(n, draft["variants"][n], why, bounds) for n in S.CREATE_NETWORKS if n in draft["variants"])
    if not texts:
        texts = f'<p class="empty">{esc(S.CREATE_JS["before_texts"])}</p>'
    body = (f'<div class="create-draft" data-create="{data}"><div class="create-alerts">{_create_notice(why)}{error_html}</div>'
            f'<div class="create-columns">'
            f'<div class="create-photo"><img src="{esc(photo_url(draft["folder"], draft["photo"], "view"))}" alt="Фото для поста"></div>'
            f'<section class="create-topic"><div class="topic-heading"><h2>Тема</h2>'
            f'<div class="create-actions">'
            f'{_spend_button("topics", topic_button + " · " + bounds["topics"], why["topics"], **topics_hidden)}'
            f'{_spend_button("voice", S.CREATE_JS["voice"] + " · " + bounds["voice"], why["voice"], aria_pressed="false")}'
            f'</div><p class="ai-status small" role="status"></p>'
            f'<p class="voice-status small" role="status"></p></div>'
            f'<div class="topic-cards">{"".join(topics)}</div>'
            f'<div class="topic-label"><label for="topic">Тема поста — выберите карточку или напишите свою</label>'
            f'<span class="topic-count small mono" hidden></span><span class="topic-save small" role="status"></span></div>'
            f'<textarea id="topic" rows="2">{esc(draft["topic"])}</textarea>'
            f'<div class="expand-row">'
            f'{_spend_button("expand", expand + " · " + bounds["expand"], why["expand"] or (S.CREATE_JS["empty_topic"] if not draft["topic"].strip() else ""), cls="btn green")}'
            f'<p class="topic-hint muted small"{" hidden" if draft["topic"].strip() else ""}>{esc(S.CREATE_JS["empty_topic"])}</p></div>'
            f'</section><section id="texts" class="create-texts"><div class="texts-heading"><h2>Тексты</h2>'
            f'<p class="text-ai-status small" role="status"></p></div>'
            f'<div class="text-cards">{texts}</div></section></div>'
            f'<p><a href="/create">Новый пост</a> · <a href="/create/profile">Профиль автора</a></p>'
            f'<noscript><p>{esc(S.CREATE_NEED_JS)}</p></noscript></div>')
    date = config.parse_utc(draft["updated"])
    return page(ctx, "create", body, sub=f'Черновик · {esc(S.day_short(date))}, {date:%H:%M}',
                sub_right=month, scripts=("author.js", "create.js"))


def create_profile(ctx: Ctx, refusal=None) -> str:
    from factory.authoring import profile
    why, bounds, month, author = _author_state(ctx)
    if refusal:
        author = refusal["values"]
    def box(name, label, limit):
        value = profile.value(author, name)
        rows = max(3, min(12, len(value) // 40 + value.count("\n") + 2))
        return (f'<div class="profile-field"><label for="profile-{esc(name)}"><span>{esc(label)}</span>'
                f'<span class="muted small limit">до {limit} знаков</span></label>'
                f'<textarea id="profile-{esc(name)}" name="{esc(name)}" rows="{rows}">{esc(value)}</textarea></div>')
    fields = "".join(box(name, label, limit) for name, label, limit, _ in profile.FIELDS)
    note = '<p class="k-ok" role="status">Профиль сохранён</p>' if ctx.q("saved") == "1" else ""
    error = f'<p class="k-bad" role="alert">{esc(refusal["error"])}</p>' if refusal else ""
    body = (f'<section class="create-profile"><h2>Профиль автора</h2><p>{esc(S.CREATE_PROFILE_HINT)}</p>{note}{error}'
            f'<form method="post" action="/create/profile">{hidden(ctx)}<div class="profile-fields">{fields}</div>'
            f'<button class="btn" type="submit">Сохранить профиль</button> <a class="btn" href="/create">Создать пост</a>'
            f'</form></section>')
    return page(ctx, "create", body, sub="Профиль автора", sub_right=month)
