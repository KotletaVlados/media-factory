"""Reviewed Gemini Standard prices, USD per million tokens, read 2026-11-12.
Source: https://ai.google.dev/gemini-api/docs/pricing
Thinking is billed at the output rate. Existing ledger rows keep their dollars.
"""
import datetime as dt
from decimal import Decimal
from factory.authoring.prompts import IMAGE_MODEL, TEXT_MODEL, VOICE_MODEL


def rates(model, now):
    if model == TEXT_MODEL:
        after = now.astimezone(dt.timezone.utc).date() >= dt.date(2027, 1, 1)
        return (Decimal("1.50"), Decimal("7.50")) if after else (Decimal("0.75"), Decimal("3.75"))
    if model == VOICE_MODEL:
        return Decimal("0.30"), Decimal("2.50")
    if model == IMAGE_MODEL:
        # Image output is $30.00/MTok (2K = 1 680 tokens); every output and thought token is
        # charged at that rate until LC3 splits the usage by modality (authoring.md §18 D32).
        return Decimal("1.50"), Decimal("30.00")
    raise ValueError("unknown Gemini model")


def cost(model, tokens_in, tokens_out, now):
    a, b = rates(model, now)
    return (a * tokens_in + b * tokens_out) / 1_000_000
