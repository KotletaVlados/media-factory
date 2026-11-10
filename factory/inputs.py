"""Read everything the planner needs, once per command (design factory.md §5.3).

Every read here is read-only: it never creates a folder or a file, so `tick --dry-run`,
`plan`, `check` and `status` leave the disk as they found it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from poster import config, state as poster_state
from poster.redact import Redactor
from factory import journal as fjournal, ruleset as fruleset, stock as fstock
from factory.paths import Paths


@dataclass
class Inputs:
    paths: Paths
    env: dict
    settings: config.Settings
    ruleset: fruleset.RuleSet
    stock: fstock.Stock
    records: list
    journal: list
    x_spent: dict          # "YYYY-MM" -> Decimal, from the poster's X ledger


def x_month_totals(poster_state_dir: str, clock) -> dict:
    ledger = poster_state.ReadOnlyLedger(poster_state_dir, clock)
    months = {row.get("month") for row in poster_state.read_jsonl(ledger.path)
              if isinstance(row.get("month"), str)}
    months.add(ledger.month())
    return {m: ledger.month_total(m) for m in sorted(months)} or {ledger.month(): Decimal(0)}


def load_env(paths: Paths, redactor: Redactor) -> dict:
    env = config.load_env(paths.env_file)
    redactor.add_env(env)
    return env


def load(paths: Paths, clock, redactor: Redactor) -> Inputs:
    """Raises config.ConfigError (env file) or ruleset.RulesError (rules file)."""
    env = load_env(paths, redactor)
    settings = config.load_settings(env)
    rules = fruleset.load(paths.rules)
    stock = fstock.load(paths.stock, paths.library, paths.packages)
    records = poster_state.read_jsonl(os.path.join(paths.poster_state, poster_state.RECORD_FILE))
    journal = poster_state.read_jsonl(os.path.join(paths.state, fjournal.RUNS))
    return Inputs(paths, env, settings, rules, stock, records, journal,
                  x_month_totals(paths.poster_state, clock))
