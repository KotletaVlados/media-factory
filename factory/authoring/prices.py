"""Reviewed Gemini Standard prices, USD per million tokens, read 2026-11-12.
Source: https://ai.google.dev/gemini-api/docs/pricing
Thinking is billed at the output rate. Existing ledger rows keep their dollars.
"""
import datetime as dt
from decimal import Decimal
from factory.authoring.prompts import TEXT_MODEL, VOICE_MODEL


def rates(model, now):
    if model == TEXT_MODEL:
        after = now.astimezone(dt.timezone.utc).date() >= dt.date(2027, 1, 1)
        return (Decimal("1.50"), Decimal("7.50")) if after else (Decimal("0.75"), Decimal("3.75"))
    if model == VOICE_MODEL:
        return Decimal("0.30"), Decimal("2.50")
    raise ValueError("unknown Gemini model")


def cost(model, tokens_in, tokens_out, now):
    a, b = rates(model, now)
    return (a * tokens_in + b * tokens_out) / 1_000_000
