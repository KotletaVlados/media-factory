"""One Gemini boundary: request, reply validation, reservation and settlement (§8, §11).

No retries, no originals, no filenames, no audio on disk. A transport is injected for
all tests and visual fixtures. Only the real transport sends HTTPS requests.
"""
from __future__ import annotations

import base64
import json
import os
import struct
import threading
import unicodedata
from contextlib import contextmanager

from poster import config, http, rules
from factory.authoring import budget, drafts, photos, prices, profile, prompts
from factory.authoring.common import Refusal, text

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
REVISION = "2026-05-20"
TIMEOUT = 120
INCOMPLETE = "ответ Gemini обрезан — повторите"
INVALID = "Gemini вернул неполный ответ — повторите"
OFFLINE = "нет связи с Gemini — повторите"
WHAT = {"topics": "темы", "expand": "тексты", "regenerate": "новый текст", "voice": "расшифровку голоса"}
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
        return value, path
    except (ValueError, TypeError, KeyError):
        raise Refusal(INVALID, 502) from None


def image(stock, draft):
    path = photos.file_path(stock, draft["folder"], draft["photo"], "view")
    if path is None or rules.sniff(path).format != "jpeg":
        raise Refusal("копия фото недоступна — загрузите фото заново")
    with open(path, "rb") as fh:
        data = fh.read(photos.LIMITS["view"] + 1)
    if len(data) > photos.LIMITS["view"]:
        raise Refusal("копия фото слишком большая")
    # Marker walk, bounded at 64 KB of headers; entropy-coded bytes are never searched.
    pos = 2
    while pos < min(len(data), 65536):
        if data[pos] != 0xff:
            raise Refusal("неверная копия фото — загрузите фото заново")
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xda, 0xd9):
            return data
        if marker in range(0xd0, 0xd9) or marker == 0x01:
            continue
        if pos + 2 > len(data):
            break
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > len(data) or pos + length > 65536:
            break
        if marker == 0xe1 and data[pos + 2:pos + 8] == b"Exif\x00\x00":
            raise Refusal("копия фото содержит EXIF — загрузите фото заново")
        pos += length
    raise Refusal("неверная копия фото — загрузите фото заново")


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
    def __init__(self, paths, clock, store, ledger, redactor, transport=None):
        self.paths, self.clock, self.store, self.ledger = paths, clock, store, ledger
        self.redactor = redactor
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
            return budget.NO_KEY
        try:
            limit = budget.cap(env)
            amount = budget.button(op, self.clock())
            if self.ledger.month_total() + amount > limit:
                return self.ledger.refusal(amount, limit)
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
                # Empty/503 fixture stays concise. Reduced vendor details never escape redaction.
                # The panel says what failed, not the status of a server error; a refusal
                # (4xx) keeps its status and the reduced vendor reason. The status is in the ledger.
                message = f"Не удалось получить {WHAT[op]} от Gemini"
                if resp.status < 500:
                    detail = self.redactor().redact(http.vendor_message(resp))
                    message += f" (HTTP {resp.status}): {detail}"
                raise Refusal(message, 502)
            value, path = parse(op, data)
            # Redact before storing, including a malicious model echo of a credential.
            value = json.loads(self.redactor().redact(json.dumps(value, ensure_ascii=False)))

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
                if d.get("error", {}) and d["error"]["op"] == op:
                    d["error"] = None
            draft = self.store.update(did, apply)
            result = {"topics": draft["topics"]} if op == "topics" else (
                {"topic": draft["topic"], "transcript": value} if op == "voice" else
                {"variants": checked_variants(draft["variants"])})
            return dict(result, rid=rid, parse_path=path)
