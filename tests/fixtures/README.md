# Fixtures

- `stdin/` — Claude Code statusline JSON. `startup.json` is a real 2.1.318 capture from
  before the first API response (no `rate_limits` / `prompt_cache`, null context
  percentage), with ids and paths scrubbed.
- `usage/`, `profile/` — `/api/oauth/usage` and `/api/oauth/profile` responses per plan
  (Phase 3). Captures are scrubbed of account ids, emails and names.
