"""One persistent ledger for every Gemini operation (authoring.md §11).

Reservations survive restart. Unknown outcomes keep the bound; only definite 4xx
refusals free it. One-entry month cache is owned by the panel through this Ledger.
"""
from __future__ import annotations

import datetime as dt
import math
import json
import os
import threading
import uuid
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from poster import state, config
from factory.authoring import prices, prompts, profile
from factory.authoring.common import Refusal

FILE = "ai-ledger.jsonl"
LOCK = "ai-ledger.lock"
MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
NEXT = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
NO_KEY = "нет GEMINI_API_KEY в .env — темы, тексты и голос недоступны"
BAD_CAP = "AI_MONTHLY_CAP_USD в .env: нужно число, например 10.00"


def cap(env):
    try:
        raw = env.get("AI_MONTHLY_CAP_USD", "10.00")
        if not isinstance(raw, str) or len(raw) > 32:
            raise ValueError()
        n = Decimal(raw)
        if not n.is_finite() or n < 0:
            raise ValueError()
        return n
    except (InvalidOperation, ValueError):
        raise Refusal(BAD_CAP) from None


def model(op):
    return prompts.VOICE_MODEL if op == "voice" else prompts.TEXT_MODEL


def bound(op, prompt, now, audio_size=0):
    # The response schema can contribute to input tokens too; include its full UTF-8
    # bytes plus framing, instead of counting only the human-facing prompt.
    schema = json.dumps(prompts.SCHEMAS.get(op, {}), ensure_ascii=False)
    tokens = len(prompt.encode("utf-8")) + len(schema.encode("utf-8")) + 512
    tokens += math.ceil(audio_size * 8 / 6000) * 32 if op == "voice" else 1120
    return prices.cost(model(op), tokens, prompts.OUTPUT[op], now)


def button(op, now):
    # Use the real template and 4-byte characters at every field limit. Reserve all
    # networks' rules in regen's bound even though the request carries only one.
    author = {"audience": {}}
    for name, _, limit, _ in profile.FIELDS:
        if name.startswith("audience."):
            author["audience"][name.split(".")[1]] = "\U00010000" * limit
        else:
            author[name] = "\U00010000" * limit
    draft = {"topic": "\U00010000" * 2000,
             "variants": {n: {"text": "\U00010000" * 5000} for n in prompts.RULES}}
    candidates = [prompts.build(op, author, draft, n, "\U00010000" * 200) for n in prompts.RULES]
    worst = max(bound(op, p, now, 1024 * 1024 if op == "voice" else 0) for p in candidates)
    after = now.astimezone(dt.timezone.utc).date() >= dt.date(2027, 1, 1)
    published = {"topics": "0.04" if after else "0.02", "expand": "0.09" if after else "0.05",
                 "regenerate": "0.09" if after else "0.05", "voice": "0.02"}
    return max(Decimal(published[op]), worst.quantize(Decimal("0.01"), rounding=ROUND_CEILING))


class Ledger:
    def __init__(self, state_dir, clock):
        self.state_dir, self.clock = state_dir, clock
        self.path = os.path.join(state_dir, FILE)
        self._key, self._total = None, Decimal(0)
        self._cache_lock = threading.Lock()

    def now(self):
        return self.clock().astimezone(dt.timezone.utc)

    def month(self):
        return self.now().strftime("%Y-%m")

    def _sum(self):
        reservations, latest = {}, {}
        for row in state.read_jsonl(self.path):
            rid = row.get("rid")
            if not rid:
                continue
            if row.get("status") == "reserved":
                reservations[rid] = row
            latest[rid] = row
        total = Decimal(0)
        for rid, row in reservations.items():
            if row.get("month") == self.month():
                final = latest[rid]
                if final.get("status") != "failed":
                    raw = final.get("actual") if final.get("status") == "ok" else row.get("price")
                    try:
                        amount = Decimal(str(raw))
                        if not amount.is_finite() or amount < 0:
                            raise InvalidOperation()
                        total += amount
                    except InvalidOperation:
                        raise Refusal("журнал бюджета ИИ повреждён — проверьте ai-ledger.jsonl") from None
        return total

    def month_total(self):
        with self._cache_lock:
            try:
                s = os.stat(self.path)
                key = (s.st_ino, s.st_mtime_ns, s.st_size, self.month())
            except FileNotFoundError:
                key = (None, self.month())
            if key != self._key:
                self._total, self._key = self._sum(), key
            return self._total

    def refusal(self, amount, limit, total=None):
        now = self.now()
        total = self.month_total() if total is None else total
        return (f"Бюджет ИИ на {MONTHS[now.month - 1]}: потрачено ${total:.2f} из ${limit:.2f}, "
                f"этот запрос — до ${amount:.2f}. Новые запросы — с 1 {NEXT[now.month % 12]} "
                "или после увеличения AI_MONTHLY_CAP_USD в .env.")

    def reserve(self, op, amount, limit, draft, admission=None):
        if not amount.is_finite() or amount < 0:
            raise Refusal("неверная стоимость запроса")
        with state.locked(self.state_dir, LOCK):
            total = self._sum()
            guard = max(amount, admission or amount)
            if total + guard > limit:
                raise Refusal(self.refusal(guard, limit, total))
            rid = str(uuid.uuid4())
            state.append_jsonl(self.path, [{"ts": config.iso_utc(self.clock()), "month": self.month(),
                "rid": rid, "vendor": "google", "model": model(op), "op": op, "draft": draft,
                "price": str(amount), "status": "reserved"}])
            return rid

    def settle(self, rid, status, *, actual=None, usage=None, http=None, interaction=None):
        row = {"ts": config.iso_utc(self.clock()), "month": self.month(), "rid": rid, "status": status}
        if actual is not None:
            row["actual"] = str(actual)
        if usage is not None:
            row["usage"] = usage
        if http is not None:
            row["http"] = http
        if interaction is not None:
            row["state"] = interaction
        with state.locked(self.state_dir, LOCK):
            state.append_jsonl(self.path, [row])

    def display(self, env):
        total = self.month_total()
        limit = cap(env)
        return f"ИИ · {MONTHS[self.now().month - 1]} ${total:.2f} из ${limit:.2f}"
