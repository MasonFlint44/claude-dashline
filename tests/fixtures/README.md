# Fixtures

- `stdin/` — Claude Code statusline JSON. `startup.json` is a real 2.1.318 capture from
  before the first API response (no `rate_limits` / `prompt_cache`, null context
  percentage), with ids and paths scrubbed. `after-first-response.json` is the same CLI
  after one turn: `rate_limits` (7d only), a warm 1h `prompt_cache`, 4% context.
- `usage/`, `profile/` — `/api/oauth/usage` and `/api/oauth/profile` responses, captured
  with `scripts/capture_fixtures.py`: `ultra` (credits on), `ultra-credits-off`,
  `enterprise` (its spend limit replaced with a placeholder). Ids, names, emails, URLs and
  dates that identify an account are scrubbed.

  dashline doesn't call the profile endpoint (it reads the copy Claude Code keeps in
  `.claude.json`); `profile/` stays as a record of the shape behind those fields.
