# Media factory

A small content factory: tools that prepare posts and publish them to social networks
through their official APIs. The first tool is the poster (`python3 -m poster`, see
`README.md` and `docs/design/poster.md`).

Machine-specific instructions, if any, live in `AGENTS.local.md` (git-ignored, optional).

## Keys

- Key values live only in `.env` in the repository root (mode 600, ignored by git).
- `KEYS.md` lists the variable names the code uses, never their values.
- Never print key values in chat, reports, commits or logs. Check that a key is present by
  its name only (for example `grep -c '^NAME=' .env`), without showing the value.

## Rules

1. Paid APIs: no bulk generation or publishing without a confirmed budget.
2. Reply to the operator in the language they write in.
