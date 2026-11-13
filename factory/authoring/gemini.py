"""One Gemini boundary: request, reply validation, reservation and settlement (§8, §11).

No retries, no originals, no filenames, no audio on disk. A transport is injected for
all tests and visual fixtures. Only the real transport sends HTTPS requests.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import threading
import unicodedata
from contextlib import contextmanager

from poster import config, http, rules
from factory.authoring import budget, drafts, photos, prices, profile, prompts
from factory.authoring.common import Refusal, jpeg_exif, text

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
REVISION = "2026-05-20"
TIMEOUT = 120
INCOMPLETE = "ответ Gemini обрезан — повторите"
INVALID = "Gemini вернул неполный ответ — повторите"
OFFLINE = "нет связи с Gemini — повторите"
WHAT = {"topics": "темы", "expand": "тексты", "regenerate": "новый текст", "voice": "расшифровку голоса",
        "highlight": "картинку"}
# D33: a 4xx is worded from its status, never from the vendor's body (the reduced vendor
# message goes to one redacted panel-log line).
REASONS = {400: "Gemini не принял запрос — подробности в журнале панели",
           401: "ключ GEMINI_API_KEY не принят — проверьте ключ и доступ к Gemini API",
           403: "ключ GEMINI_API_KEY не принят — проверьте ключ и доступ к Gemini API",
           402: "закончились предоплаченные кредиты Gemini — пополните баланс в Google AI Studio",
           404: "модель недоступна для этого ключа",
           413: "запрос слишком большой",
           429: "Gemini просит подождать — повторите позже"}
OTHER_4XX = "Gemini отклонил запрос — подробности в журнале панели"
# slice C (authoring.md §18.5 items 5 and 6)
IMAGE_TIMEOUT = 180
MAX_IMAGE = 8 * 1024 * 1024
NO_IMAGE = "Gemini не вернул картинку"
NOT_JPEG = "Gemini вернул картинку не в JPEG — повторите"
TOO_BIG = "Gemini вернул слишком большую картинку — повторите"


class NoImage(Refusal):
    """A completed reply without an image block; `model_text` is the model's text part."""

    def __init__(self, model_text):
        super().__init__(NO_IMAGE, 502)
        self.model_text = model_text


def reason(status):
    return REASONS.get(status, OTHER_4XX)

def billed_output(u):
    # G14: total_tokens disambiguates whether the output count includes thoughts.
    # With no confirming total, retain the conservative sum from §11.2.
    if u.get("total") == u["in"] + u["out"]:
        return u["out"]
    return u["out"] + u["thought"]


def usage(data):
    raw = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None
    out = {}
    for source, dest in (("total_input_tokens", "in"), ("total_output_tokens", "out"),
                         ("total_thought_tokens", "thought")):
        n = raw.get(source, 0 if dest == "thought" else None)
        if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > 100_000_000:
            return None
        out[dest] = n
    if isinstance(raw.get("total_tokens"), int):
        out["total"] = raw["total_tokens"]
    return out


def output(data):
    if not isinstance(data, dict):
        raise Refusal(INVALID, 502)
    if data.get("status") == "incomplete":
        raise Refusal(INCOMPLETE, 502)
    if data.get("status") != "completed":
        raise Refusal(INVALID, 502)
    steps = data.get("steps", [])
    steps = [s for s in steps if isinstance(s, dict) and s.get("type") == "model_output"] if isinstance(steps, list) else []
    result, path = "", "steps"
    if steps and isinstance(steps[-1].get("content"), list):
        result = "".join(b["text"] for b in steps[-1]["content"] if isinstance(b, dict)
                         and b.get("type") == "text" and isinstance(b.get("text"), str))
    if not result and isinstance(data.get("output_text"), str):
        result, path = data["output_text"], "output_text"
    if not result.strip():
        raise Refusal(INVALID, 502)
    return result, path


def parse(op, data):
    result, path = output(data)
    try:
        if op == "voice":
            if len(result) > 2000:
                raise ValueError()
            return result, path
        value = json.loads(result)
        if not isinstance(value, dict):
            raise ValueError()
        expected = {"topics"} if op == "topics" else set(drafts.LANGS) if op == "expand" else {"text"}
        quotes = value.pop("quotes", None) if op == "expand" else None
        if set(value) != expected:
            raise ValueError()
        if op == "topics":
            topics = value["topics"]
            if not isinstance(topics, list) or not 3 <= len(topics) <= 5:
                raise ValueError()
            for item in topics:
                if not isinstance(item, dict) or set(item) != {"title", "angle"}:
                    raise ValueError()
                for k, limit in (("title", 1000), ("angle", 1000)):
                    if not isinstance(item[k], str) or not item[k].strip() or len(item[k]) > limit:
                        raise ValueError()
        else:
            if any(not isinstance(v, str) or not v.strip() or len(v) > 5000 for v in value.values()):
                raise ValueError()
        if op == "expand":
            # Slice C (§18.5 item 4): the quotes are optional; a bad one is dropped, the texts stay.
            kept = {}
            if isinstance(quotes, dict):
                for n, q in quotes.items():
                    if n in drafts.LANGS and isinstance(q, str):
                        q = unicodedata.normalize("NFC", q).strip()
                        if q and not drafts.quote_problem(q):
                            kept[n] = q
            if kept:
                value["quotes"] = kept
        return value, path
    except (ValueError, TypeError, KeyError):
        raise Refusal(INVALID, 502) from None


def picture(data):
    """The first image block of the reply's `model_output` steps as base64 text (§9.2), or
    NoImage with the model's text part. `incomplete` and other states answer as §8.4."""
    if not isinstance(data, dict):
        raise Refusal(INVALID, 502)
    if data.get("status") == "incomplete":
        raise Refusal(INCOMPLETE, 502)
    if data.get("status") != "completed":
        raise Refusal(INVALID, 502)
    steps = data.get("steps", [])
    steps = [s for s in steps if isinstance(s, dict) and s.get("type") == "model_output"
             and isinstance(s.get("content"), list)] if isinstance(steps, list) else []
    words = []
    for step in steps:
        for block in step["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "image" and isinstance(block.get("data"), str):
                return block["data"]
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                words.append(block["text"])
    if not words and isinstance(data.get("output_text"), str):
        words.append(data["output_text"])
    raise NoImage(" ".join(" ".join(words).split()))


def decode_picture(encoded):
    """Base64 to JPEG bytes, at most 8 MB decoded; refusals as §18.5 item 6."""
    if len(encoded) > (MAX_IMAGE + 2) // 3 * 4 + 4:
        raise Refusal(TOO_BIG, 502)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise Refusal(NOT_JPEG, 502) from None
    if len(raw) > MAX_IMAGE:
        raise Refusal(TOO_BIG, 502)
    if not raw.startswith(b"\xff\xd8\xff"):
        raise Refusal(NOT_JPEG, 502)
    return raw


def image(stock, draft):
    path = photos.file_path(stock, draft["folder"], draft["photo"], "view")
    if path is None or rules.sniff(path).format != "jpeg":
        raise Refusal("копия фото недоступна — загрузите фото заново")
    with open(path, "rb") as fh:
        data = fh.read(photos.LIMITS["view"] + 1)
    if len(data) > photos.LIMITS["view"]:
        raise Refusal("копия фото слишком большая")
    kind = jpeg_exif(data)
    if kind == "exif":
        raise Refusal("копия фото содержит EXIF — загрузите фото заново")
    if kind != "ok":
        raise Refusal("неверная копия фото — загрузите фото заново")
    return data


def highlight_request(key, prompt, media, aspect):
    """§9.2's request with "resolution": "high" on the image block (D32)."""
    body = {"model": prompts.IMAGE_MODEL, "store": False,
            "input": [{"type": "text", "text": prompt},
                      {"type": "image", "mime_type": "image/jpeg",
                       "data": base64.b64encode(media).decode("ascii"), "resolution": "high"}],
            "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": aspect,
                                "image_size": "2K"}}
    headers = {"x-goog-api-key": key}
    if REVISION:
        headers["Api-Revision"] = REVISION
    return http.json_request("POST", URL, body, headers=headers, timeout=IMAGE_TIMEOUT, display={})


def request(op, key, prompt, media, mime):
    block = {"type": "audio" if op == "voice" else "image", "mime_type": mime,
             "data": base64.b64encode(media).decode("ascii")}
    if op != "voice":
        block["resolution"] = "high"
    body = {"model": budget.model(op), "store": False,
            "generation_config": {"thinking_level": "minimal" if op == "voice" else "low",
                                  "max_output_tokens": prompts.OUTPUT[op]},
            "input": [{"type": "text", "text": prompt}, block]}
    if op != "voice":
        body["response_format"] = {"type": "text", "mime_type": "application/json", "schema": prompts.SCHEMAS[op]}
    headers = {"x-goog-api-key": key}
    if REVISION:
        headers["Api-Revision"] = REVISION
    # The display copy carries neither credentials nor media; nobody logs the request.
    return http.json_request("POST", URL, body, headers=headers, timeout=TIMEOUT, display={})


def present(network, value):
    """The panel's count line and problems for one text, in Russian, from the poster's own
    counters and limits (no second counting rule). `line` is the short count; `problems`
    are the limits it breaks, each one red line. A text is never cut (design §8.6)."""
    if not value.strip():
        return {"line": "", "problems": ["текст пуст"]}
    bad = []

    def over(n, limit):
        if n <= limit:
            return f"{n} / {limit} знаков"
        bad.append(f"длиннее лимита: {n} / {limit} — сократите")
        return ""

    if network == "facebook":
        parts = [f"{len(value)} знаков"]
    elif network == "x":
        parts = [over(rules.x_weighted_length(value), rules.X_MAX_WEIGHTED)]
        k = rules.count_cashtags(value)
        if k > rules.X_MAX_CASHTAGS:
            bad.append(f"тегов $ в тексте {k}: X разрешает {rules.X_MAX_CASHTAGS}")
    elif network == "linkedin":
        parts = [over(rules.utf16_len(rules.linkedin_escape(value)), rules.LI_MAX_COMMENTARY)]
    else:
        parts = [over(rules.utf16_len(value), rules.IG_MAX_CAPTION)]
        h, m = rules.count_hashtags(value), rules.count_mentions(value)
        if h > rules.IG_MAX_HASHTAGS:
            bad.append(f"хештегов {h}: Instagram разрешает {rules.IG_MAX_HASHTAGS}")
        else:
            parts.append(f"хештеги {h} / {rules.IG_MAX_HASHTAGS}")
        if m > rules.IG_MAX_MENTIONS:
            bad.append(f"упоминаний {m}: Instagram разрешает {rules.IG_MAX_MENTIONS}")
        elif m:
            parts.append(f"упоминания {m} / {rules.IG_MAX_MENTIONS}")
    return {"line": " · ".join(p for p in parts if p), "problems": bad}


def checked_variants(data):
    out = {}
    for n, v in data.items():
        check = rules.check_text(n, v["text"])
        out[n] = dict(v, counts=check.counts, errors=check.errors, **present(n, v["text"]))
    return out


class Service:
    def __init__(self, paths, clock, store, ledger, redactor, transport=None, log=None):
        self.paths, self.clock, self.store, self.ledger = paths, clock, store, ledger
        self.redactor, self.log = redactor, log
        self.transport = transport if transport is not None else http.UrllibTransport()
        self.slots = threading.BoundedSemaphore(2)

    def env(self):
        return config.load_env(self.paths.env_file)

    @contextmanager
    def admission(self, did):
        with self.store.ai_lock(did):
            if not self.slots.acquire(blocking=False):
                raise Refusal("ИИ занят двумя запросами — подождите")
            try:
                yield
            finally:
                self.slots.release()

    def availability(self, op, env=None):
        env = self.env() if env is None else env
        if not env.get("GEMINI_API_KEY", "").strip():
            return budget.NO_KEY_IMAGE if op == "highlight" else budget.NO_KEY
        try:
            limit = budget.cap(env)
            amount = budget.button(op, self.clock())
            if self.ledger.month_total() + amount > limit:
                return self.ledger.refusal(amount, limit, op=op)
        except Refusal as exc:
            return exc.message
        return ""

    def run(self, did, op, *, auto=False, network="", wish="", audio=b"", mime=""):
        if op == "topics" and auto:
            current = self.store.load(did)
            if current["topics_auto"] != "pending":
                return {"topics": current["topics"], "skipped": True}
        with self.admission(did):
            draft = self.store.load(did)
            if op == "topics" and auto:
                if draft["topics_auto"] != "pending":
                    return {"topics": draft["topics"], "skipped": True}
                # Mark once before reservation, including refusals, so reload cannot spend.
                draft = self.store.update(did, lambda d: d.update(topics_auto="done"))
            env = self.env()
            why = self.availability(op, env)
            if why:
                raise Refusal(why)
            if op in ("expand", "regenerate") and not draft["topic"].strip():
                raise Refusal("выберите тему или впишите свою")
            if op == "regenerate" and network not in draft["variants"]:
                raise Refusal("сначала разверните тему")
            if op == "voice":
                if not ((mime == "audio/webm" and audio.startswith(b"\x1a\x45\xdf\xa3")) or
                        (mime == "audio/ogg" and audio.startswith(b"OggS"))):
                    raise Refusal("неверная запись голоса", 415)
                media = audio
            else:
                media, mime = image(self.paths.stock, draft), "image/jpeg"
            author = profile.load(self.paths.content)
            prompt = prompts.build(op, author, draft, network, wish)
            now = self.clock()  # The price period belongs to reservation, not the later reply.
            amount = budget.bound(op, prompt, now, len(audio))
            rid = self.ledger.reserve(op, amount, budget.cap(env), did, admission=budget.button(op, now))
            try:
                req = request(op, env["GEMINI_API_KEY"], prompt, media, mime)
                req.fields = {"op": op, "draft": did}
                resp = self.transport.send(req)
            except (http.TransportError, TimeoutError, OSError):
                self.ledger.settle(rid, "unknown")
                raise Refusal(OFFLINE, 504) from None
            data = resp.json()
            u = usage(data)
            state = data.get("status", "") if isinstance(data, dict) else ""
            if state not in ("completed", "incomplete", "failed", "cancelled", "in_progress",
                             "requires_action", "requires_continuation"):
                state = "invalid"
            if resp.ok and u is not None:
                actual = prices.cost(budget.model(op), u["in"],
                                     billed_output(u), now)
                self.ledger.settle(rid, "ok", actual=actual, usage=u, http=resp.status, interaction=state)
            else:
                self.ledger.settle(rid, "failed" if 400 <= resp.status < 500 else "unknown",
                                   http=resp.status, interaction=state)
            if not resp.ok:
                self.refused(op, resp)
            value, path = parse(op, data)
            # Redact before storing, including a malicious model echo of a credential.
            value = json.loads(self.redactor().redact(json.dumps(value, ensure_ascii=False)))
            quotes = value.pop("quotes", {}) if op == "expand" else {}

            def apply(d):
                if op == "topics":
                    d["topics"] = value["topics"]
                elif op == "voice":
                    d["topic"] = text((d["topic"] + " " + value).strip(), 2000, "тема")
                else:
                    texts = value if op == "expand" else {network: value["text"]}
                    if op == "expand":
                        d["variants"] = {}
                    for n, t in texts.items():
                        d["variants"][n] = {"text": unicodedata.normalize("NFC", t), "lang": drafts.LANGS[n], "source": "gemini"}
                    if quotes:
                        # A changed quote that a network draws drops that network's crop (D30).
                        before = json.loads(json.dumps(d))
                        d["quotes"] = dict(d.get("quotes") or {}, **quotes)
                        drafts.drop_changed(self.store.path(did), before, d, drafts.CHOICES)
                if d.get("error", {}) and d["error"]["op"] == op:
                    d["error"] = None
            draft = self.store.update(did, apply)
            result = {"topics": draft["topics"]} if op == "topics" else (
                {"topic": draft["topic"], "transcript": value} if op == "voice" else
                {"variants": checked_variants(draft["variants"])})
            return dict(result, rid=rid, parse_path=path)

    def refused(self, op, resp):
        """Raise the Russian line for a failed reply (D33). A 4xx says what to do by its
        status; the reduced vendor message goes only to one redacted panel-log line. A
        5xx keeps B′'s line without a status."""
        message = f"Не удалось получить {WHAT[op]} от Gemini"
        if resp.status < 500:
            detail = self.redactor().redact(http.vendor_message(resp))
            if self.log is not None:
                print(self.redactor().redact(f"panel: gemini {op} HTTP {resp.status}: {detail}"),
                      file=self.log, flush=True)
            message += f" (HTTP {resp.status}): {reason(resp.status)}"
        raise Refusal(message, 502)

    def highlight(self, did, style, who, sender):
        """POST /create/<id>/highlight (§18.5 items 5–7): one Gemini image call for one style,
        reserved before it is built and sent. The result is stored as img/<style>.jpg by
        `sender.store_style`; a draft sent meanwhile stores nothing (409)."""
        if style not in drafts.STYLES:
            raise Refusal("неверный стиль", 400)
        if not isinstance(who, str):
            raise Refusal("неверный запрос", 400)
        who = " ".join(unicodedata.normalize("NFC", who).split())
        if len(who) > drafts.WHO_MAX:
            raise Refusal(f"кто главный: не больше {drafts.WHO_MAX} знаков")
        op = "highlight"
        with self.admission(did):
            draft = self.store.load(did)
            if draft["state"] != "draft":
                raise Refusal(drafts.SENT)
            if (draft.get("who") or "") != who:
                def keep(d):
                    if who:
                        d["who"] = who
                    else:
                        d.pop("who", None)
                draft = self.store.update(did, keep)
            env = self.env()
            why = self.availability(op, env)
            if why:
                raise Refusal(why)
            media = image(self.paths.stock, draft)
            view = photos.file_path(self.paths.stock, draft["folder"], draft["photo"], "view")
            info = rules.sniff(view)
            aspect = prompts.aspect(info.width, info.height)
            prompt = prompts.highlight(style, who)
            now = self.clock()
            amount = budget.bound(op, prompt, now)
            rid = self.ledger.reserve(op, amount, budget.cap(env), did, admission=budget.button(op, now))
            try:
                req = highlight_request(env["GEMINI_API_KEY"], prompt, media, aspect)
                req.fields = {"op": op, "draft": did, "style": style}
                resp = self.transport.send(req)
            except (http.TransportError, TimeoutError, OSError):
                self.ledger.settle(rid, "unknown")
                raise Refusal(OFFLINE, 504) from None
            data = resp.json()
            u = usage(data)
            state = data.get("status", "") if isinstance(data, dict) else ""
            if state not in ("completed", "incomplete", "failed", "cancelled", "in_progress",
                             "requires_action", "requires_continuation"):
                state = "invalid"
            if resp.ok and u is not None:
                actual = prices.cost(prompts.IMAGE_MODEL, u["in"], billed_output(u), now)
                self.ledger.settle(rid, "ok", actual=actual, usage=u, http=resp.status, interaction=state)
            else:
                self.ledger.settle(rid, "failed" if 400 <= resp.status < 500 else "unknown",
                                   http=resp.status, interaction=state)
            if not resp.ok:
                self.refused(op, resp)
            try:
                raw = decode_picture(picture(data))
            except NoImage as exc:
                exc.model_text = self.redactor().redact(exc.model_text)[:300]
                raise
            stored, info = sender.store_style(did, style, raw)
            return {"style": style, "width": info.width, "height": info.height,
                    "url": f"/create/{did}/file?name={style}", "base": stored.get("base", "orig")}
