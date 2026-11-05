# dashline — plan

Status: draft 4, 2026-11-04. Nothing built yet.

Repo `~/git/claude-dashline`; plugin `dashline` (skills `/dashline:install`,
`/dashline:doctor`); Python package `dashline`.

One Claude Code statusline plugin for every account type: Free (trial), Pro,
Max, Ultra, Team, Enterprise, plus API-key and gateway sessions. It's meant to
replace the author's earlier statusline plugins, but **dashline knows nothing
about them**: no migration code, no references to their files, settings or
caches. It will be listed in the `claude-toolbox` marketplace eventually.

Facts marked **(verified)** were read from the Claude Code 2.1.318 binary or
from live calls to the endpoints on 2026-11-03.

## Decisions so far

| Topic | Decision |
|---|---|
| Runtime | Python ≥ 3.9, standard library only, no tqdm |
| Dev tooling | `uv`; `ruff` (format, lint, import sorting); `pytest`. Tests are required |
| Refresh | `statusLine.refreshInterval: 60` |
| Bars | `▆` fill in one solid ramp color + `▁` empty in theme gray, whole cells (min 1 when > 0%) (§4) |
| Which bars | **data-driven** from the usage endpoint's `limits[]`, not a plan table |
| Plan label | from the server (`plan_display_name`), e.g. "Ultra" |
| Enterprise / Team spend | a simple monthly bar; no day bar, no holiday calendar |
| Model-scoped bar (Fable) | shown while the current model is in scope, including at 0% |
| Pace tick | out for v1; possible later feature |
| Install path | `${CLAUDE_CONFIG_DIR:-~/.claude}/scripts/statusline/` |
| Config file | none in v1; if ever needed, `${CLAUDE_CONFIG_DIR:-~/.claude}/config/statusline/` |
| Layout | E3 (§4): line 1 session + `context` bar, line 2 plan name + plan bars, line 3 repo |
| Bar widths | plan bars shared 8–24; `context` = 2× plan width; overflow moves trailing bars up only when needed; never wraps |
| Separators | `·` between items, `│` between groups, both in theme gray (ascii: `/`, `\|`) |
| Directory row | option C (§5): icons + uncommitted line delta only |
| Glyphs | `--glyphs nerd\|unicode\|ascii` flag in the statusLine command, default `unicode`; no config file in v1 |
| Fast-mode glyph | 󱐋 md-lightning_bolt (U+F140B); `↯` in the unicode set |

---

## 1. What Claude Code gives us

### Statusline stdin (verified)

| Need | Field |
|---|---|
| model | `model.display_name`, `model.id` |
| effort | `effort.level`: `low` / `medium` / `high` / `xhigh` / `max` (absent when the model has no effort setting) |
| fast mode | `fast_mode` (bool; present in the input but missing from the documented schema) |
| session cost | `cost.total_cost_usd` (read from one process-wide cost ledger; Phase 0, E1, checks whether subagents are included) |
| session churn | `cost.total_lines_added` / `total_lines_removed` (Claude's Edit/Write lines) |
| context | `context_window.used_percentage`, `context_window_size` |
| prompt cache | `prompt_cache.{warm, caching_observed, ttl, expires_at, recache_tokens_if_cold, last_miss_cause}` |
| plan windows | `rate_limits.five_hour` / `seven_day` (subscribers) |
| gateway spend | `rate_limits.spend_limit.{used_percentage, used_usd, limit_usd, period, resets_at}` |
| session name | `session_name` (set via `/rename`) |
| agent | `agent.name` (only with `--agent`) |
| project dir | `workspace.project_dir` |
| worktree | `workspace.git_worktree`, `worktree.{name, path, branch}` |
| repo identity | `workspace.repo.{host, owner, name}` |

### Refresh (verified)

`refreshInterval` re-runs the command every N seconds **on top of** the event-driven
updates. The CLI also re-runs it 1 s after the earliest of `prompt_cache.expires_at`
and any `rate_limits.*.resets_at`. Events (debounced 300 ms) also trigger a re-run: new message, model,
effort, fast mode, permission mode, vim mode, PR status.

### Plan identity (verified)

- **Label (changed in Phase 3, 11/4):** the CLI already fetches `GET /api/oauth/profile`
  and caches it in `.claude.json` → `oauthAccount` (`planDisplayName`,
  `organizationType`, `organizationRateLimitTier`, `seatTier`, `claudeCodeTrialEndsAt`,
  `accountUuid`, `organizationUuid`, `profileFetchedAt`), refreshing it itself. So a
  render reads that one local file (under `CLAUDE_CONFIG_DIR` if set, else `~`) and
  dashline never calls the profile endpoint. `plan_display_name` is `"Ultra"` for this
  account; the CLI itself still calls the tier `default_claude_max_20x`.
- **Enterprise has no `plan_display_name`** (E6 capture): the profile gives
  `organization_type: "claude_enterprise"`, `seat_tier: "enterprise_usage_based"`,
  `rate_limit_tier: "default_claude_zero"`. When the name is missing, map
  `organizationType` (`claude_enterprise`→Enterprise, `claude_team`→Team, assumed by
  analogy until a Team capture; `claude_pro`→Pro; `claude_max`→Max, Ultra on a `20x`
  rate tier), then the credentials file's `subscriptionType` + `rateLimitTier`
  (same table).
- **Trial:** `claudeCodeTrialEndsAt` (ISO) is a Claude Code trial on a Pro
  subscription (the CLI's `Trial: N days left`). While it runs the label reads
  `Pro · trial 5d` (`trial 7h` on the last day).
- **Team seats:** the profile has `seat_tier`, and the CLI treats a Team seat on the
  `max_5x` rate tier as premium. The label comes from `plan_display_name`, so we
  don't need our own mapping.
- **API mode (no plan bars, no fetch):** `CLAUDE_CODE_USE_BEDROCK` / `VERTEX` /
  `FOUNDRY` → `Bedrock` / `Vertex` / `Foundry` (the other provider flags → `API`);
  stdin `rate_limits.spend_limit` (sent only behind a gateway) → `Gateway` with a
  `month` bar; `ANTHROPIC_AUTH_TOKEN`, an `ANTHROPIC_API_KEY` the user approved
  (`customApiKeyResponses.approved` holds its last 20 chars), or no `oauthAccount` and
  no `CLAUDE_CODE_OAUTH_TOKEN` → `API`. Plan windows on stdin override all but the
  provider flags: the CLI sends them only to subscribers.
- **Token (background fetch only, never a render):** `CLAUDE_CODE_OAUTH_TOKEN`, then
  on macOS the Keychain (`security find-generic-password -a $USER -w -s "Claude
  Code-credentials"`, with `-<sha256(CLAUDE_CONFIG_DIR)[:8]>` appended when that is
  set; account `claude-code-user` if `$USER` isn't `[A-Za-z0-9._-]+`), then
  `<config>/.credentials.json` → `claudeAiOauth.accessToken`. A token within 60 s of
  `expiresAt` counts as expired: the CLI renews it on its next request.

### Usage endpoint (verified live)

`GET /api/oauth/usage` (bearer token, `anthropic-beta: oauth-2025-04-20`).
It's undocumented, so any shape change must degrade to a hidden bar, never a crash.

- `limits[]` — the server's meters for this account: `kind` (`session`,
  `weekly_all`, `weekly_scoped`, …), `percent`, `severity`, `resets_at`,
  `scope.model.display_name`.
- `spend` — usage credits / extra usage: `used`, `limit`, `percent`,
  `enabled`, plus `extra_usage.spend_limit_reached`.
- Rows come and go: `five_hour` was `null` today on Ultra with no active window.

---

## 2. Runtime and tooling

- Python ≥ 3.9 (macOS command-line tools ship 3.9.6), standard library only. Imports are lazy in
  `__main__`. Budget: 40 ms per render with a warm cache.
- No tqdm: we draw the bar ourselves (a few lines: `▆` fill and `▁` empty in
  whole cells, one color; see §4).
- Network: `urllib` in a detached background child; the render never waits on
  the network. The token stays in-process (never in argv, env or disk).
- `pyproject.toml` with dev dependencies (`ruff`, `pytest`) under uv; `uv run
  ruff format`, `uv run ruff check`, `uv run pytest`. Ruff rules: `E F W I UP B
  SIM RUF PTH`, `target-version = "py39"`.
- CI (GitHub Actions): ruff format check + lint, pytest on 3.9 / 3.12 / 3.14 ×
  ubuntu + macOS, and a check that the README preview is current.

---

## 3. Install layout

```
${CLAUDE_CONFIG_DIR:-~/.claude}/scripts/statusline/
  statusline.py          entry shim: puts its dir on sys.path, runs the package
  dashline/              package, copied from the plugin
  VERSION
${CLAUDE_CONFIG_DIR:-~/.claude}/cache/statusline/
  usage.json  fetch.lock  fetch.hold
```

Fetching (Phase 3): a render that finds `usage.json` missing or ≥ 3 min old, and no
`fetch.hold` in force for this login, takes `fetch.lock` (O_EXCL; a lock ≥ 60 s old
belongs to a dead child) and, after printing, starts a detached `python3 -I -S` child
(new session, stdio on /dev/null, no token in argv). The child fetches once and writes
`usage.json` `{fetched_at, account, data}` or `fetch.hold` `{until, reason, failures,
account}`. `account` is a hash of the account and org ids, so a different login never
sees another's numbers. Holds: no login 10 min, expired token / 401 5 min, 403 1 h,
404 6 h; anything else backs off 1, 2, 4 … 30 min (`Retry-After` honored on 429).
Data older than a day is dropped. Files are 0600 in a 0700 directory, written
atomically.

settings.json, written literally so a devcontainer mounting `~/.claude` under
another user still resolves it:

```json
"statusLine": {
  "type": "command",
  "command": "python3 -I -S \"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/scripts/statusline/statusline.py\"",
  "refreshInterval": 60
}
```

The package is copied, not symlinked, because the plugin cache path changes per version. Doctor
flags a stale copy.

---

## 4. Lines 1–2 — session and account (layout E3, chosen 11/4)

One subject per line:

```
Fable 5.1 · xhigh · $11.80 │ context ▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ 63%
Ultra │ 5h ▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ 22%  7d ▆▆▆▆▆▆▆▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁ 48%  Fable ▆▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ 24%
󰊢 claude-dashline  󰘬 feat/cache  󱓎 rebasing 3/7  󰀦 2
```

1. **Session (placement P3, settled 11/4):**
   `model · effort fast · agent · cost │ context ▆▆▆▁▁▁ 41% <cache state>`.
   A dot goes between model and effort (matches Claude Code's own footer); no dot
   between effort and the fast glyph. The
   cache state sits right after the context bar. It's about the prompt, and its
   changing length (`󰔟 3m`, `󰜗 cold (tools changed) 󰑐38k`) can't shift anything
   when it's at the end of the line.
2. **Account:** the plan name (dim) heads the plan's bars. Without plan bars
   (API key, gateway with no limit) this line disappears, and the plan name moves
   next to the model on line 1: `Sonnet 5.5 · medium · API · $0.57 │ context …`
   (settled 11/4).
3. **Repo:** §5.

**Separators (settled 11/4), in Claude Code's `inactive` gray for the active theme (§4a):**
`·` between text items, `│` (U+2502 box-drawing light vertical) between groups
(line 1: text │ bars; line 2: plan name │ bars), two spaces between bars. Lines
are not column-aligned with each other (rejected 11/4).

```
Opus 5.5 · high 󱐋 · $4.12 │ context ▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ 41%
Ultra │ 5h ▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁ 22%  7d ▆▆▆▆▆▆▆▆▆▆▆▆▁▁▁▁▁▁▁▁▁▁▁▁ 48%
󰊢 claude-dashline  󰘬 feat/cache  󰏫 +120 −45  󰜷2
```

Earlier candidates, mocked and rejected or parked: A (everything on line 1, bars wrap),
B (grouped on one line), C (bars first), D (basics line + all bars on a line),
E1 (plan name on line 1), E2 (bars stretch to fill each line).

| Element | Source | Rendering |
|---|---|---|
| model | `model.display_name` | bright |
| effort | `effort.level` | low grey · medium green · high gold · xhigh coral · max coral bold |
| fast | `fast_mode` | 󱐋 gold, hidden when off |
| agent | `agent.name` | dim `󱙺 code-reviewer`, only with `--agent` |
| cost | `cost.total_cost_usd` | `$4.12` |
| cache | `prompt_cache` | hidden while warm and not close to expiry; gold `󰔟 8m` within **10 min** of expiry on a 1h cache, **1 min** on a 5m cache (settled 11/4); coral `󰜗 cold (tools changed) 󰑐38k` when cold. Hidden when `caching_observed` is false |
| plan | `.claude.json` `oauthAccount` / credentials | dim, heads line 2; `· trial 5d` appended during a trial |

### Bars

| Bar | Line | Source | Shown when |
|---|---|---|---|
| `context` | 1 | stdin `context_window.used_percentage` | after the first response |
| `5h` | 2 | `limits[kind=session]`, fallback stdin `five_hour` | the row exists |
| `7d` | 2 | `limits[kind=weekly_all]`, fallback stdin `seven_day` | the row exists |
| model-scoped (`Fable`, …) | 2 | `limits[kind=weekly_scoped, scope.model]` | current model matches the scope, even at 0% |
| `credits` | 2 | endpoint `spend` | enabled and used > 0 |
| `month` | 2 | endpoint `spend` on Team/Enterprise caps; stdin `spend_limit` behind a gateway | the account has a monthly cap (shown at 0% too; Enterprise's `limits[]` is empty, so this is its only bar) |

Unknown `kind`s are rendered by their server label rather than dropped. That is
how a new meter shows up without a release.

### Bar style (settled 11/4)

- **Fill:** `▆` (lower 3/4 block), one solid color per bar from a ramp over three
  anchors: Claude Code's `success` (green) → `warning` (gold) → `error` (coral) for the
  active theme (§4a). Flat green up to the first anchor, a continuous blend green→gold
  →coral between anchors, flat coral past the last (settled 11/4). **Anchors (option B,
  settled 11/4): flat green up to 40%, pure gold at 70%, flat coral from 90%.** Always truecolor; the CLI downsamples it when the terminal can't show it (E7).
- **Empty part:** `▁` (lower 1/8) in Claude Code's `subtle` gray for the active theme
  (replaces the earlier ANSI-8 choice, 11/4). Its shape differs
  from the fill, so the bar still reads with `NO_COLOR`.
- **Whole cells only**, rounded to the nearest cell, halves up (no partial blocks). Any value above 0% shows at least one
  filled cell, and the bar is full only at 100% (at most width − 1 cells below it); likewise
  the percent never reads `100%` before the limit (Phase 2). Height-stepped edge cells (`▁▂▃▄▅`) were tried and rejected 11/4.
- Why not full blocks: `█` fills the whole cell, so the context bar on line 1 and the
  plan bars on line 2 touched and blended. The 3/4 block leaves a gap above each bar.
- Rejected on the way: heavy line `━`, braille, parallelograms/squares (look varies by font),
  `░` shades (full height), any track gray derived from the user's background.

### Rules

- **Widths, no wrapping (settled 11/4).** Plan bars share one width (cap 24,
  minimum 8), so they stay comparable side by side; `credits` keeps that width even
  when it moves to line 1. The `context` bar is **2× the plan-bar width**
  (so at most 48, minimum 8; no separate cap), limited by the room left on line 1
  (e.g. a cold-cache message can shrink it). With no plan bars, context takes
  line 1's room up to 48, the same as 2× a full-width plan bar.
  1. If every plan bar fits on line 2 at ≥ 8 and `context` fits on line 1 at
     ≥ 8, use the largest widths that fit.
  2. Otherwise the trailing plan bars move to the end of line 1, after
     `context`, one at a time (`credits` first, since it's last), until both
     lines fit at ≥ 8. Bars move only when needed.
  3. If nothing fits at 8, every bar collapses to `label NN%` (text only) on
     its usual line. Nothing moves.
  4. Extremely narrow (the text-only line still doesn't fit): drop reset countdowns,
     then cut the line short with `…`.
  Bars resizing when line-1 text changes (e.g. the cache warning) is fine
  (settled 11/3). Known quirk, accepted 11/4: moving a bar up can make the bars *wider*
  at a narrower terminal (e.g. 4 bars: 8 wide at 100 cols, 12 wide at 90 cols
  with `credits` moved up). Bars move only when needed, never just to get wider.
- Terminal width = `COLUMNS` minus the TUI frame reserve: **4** in 2.1.318 (E5:
  2-col indent + 2 at the right; a line of exactly `COLUMNS − 4` fits, one more is
  cut with `…`). `COLUMNS` is passed to the command as the full terminal width.
- **Reset countdown** `(1h40m)` after a bar at ≥ **70%**, the gold anchor, so color and
  countdown change together (settled 11/4).
- **Limit reached:** a window at 100% with credits off or exhausted shows
  coral `limit · resets 2h10m` instead of a bare full bar.
- **Stale data:** usage cache > 5 min old (fetch failing) → dim `·12m` after
  the last bar on line 2 (settled 11/4; ascii `~12m`).
- **Both sources (Phase 3):** `5h` / `7d` come from the endpoint and from stdin. stdin
  arrives with every API response, so it is often fresher: for the same window
  (`resets_at` within 60 s) the higher percent wins, otherwise the later window. A
  cached row whose `resets_at` has passed reads 0%.
- Past 100% (credits, gateway spend): the bar stays full and the percent keeps counting.

### Narrow terminals

Line 1 drop order: agent → cache text (glyph stays). Model, effort, cost and
the context bar never drop. Bars follow the overflow rule above. They never wrap
to a fourth line.

---

## 4a. Colors: Claude Code's theme (settled 11/4)

Every color in dashline comes from the Claude Code theme the user picked, so the
statusline matches the rest of the UI. No dashline-specific palette.

**Which theme (E8, read from the 2.1.318 binary):** the stdin JSON carries no theme, so
dashline resolves it the way the CLI does:

1. The `theme` key in the settings files, highest priority first: managed/policy →
   `<project>/.claude/settings.local.json` → `<project>/.claude/settings.json` →
   `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`. `/config` writes to user settings.
   (Flag settings from `--settings` can't be seen from the statusline; ignore them.)
2. Legacy: the `theme` key in `~/.claude.json` (older installs), if not `dark`.
3. Default `dark`.

Values: `auto`, `dark`, `light`, `dark-daltonized`, `light-daltonized`, `dark-ansi`,
`light-ansi`, or `custom:<slug>`.

- **`auto`:** the CLI asks the terminal for its background (OSC 11, luminance > 0.5 →
  light), then `COLORFGBG` (last field ≤ 6 or 8 → dark), then `dark`. A statusline has
  no tty to ask, so dashline uses `COLORFGBG`, else `dark`. Known gap: `auto` on a
  light terminal that doesn't set `COLORFGBG` renders with the dark palette; doctor says so.
- **Custom themes:** `custom:<slug>` → `${CLAUDE_CONFIG_DIR:-~/.claude}/themes/<slug>.json`
  `{ "name", "base", "overrides": { token: color } }`. `base` is a built-in name (default
  `dark`); `overrides` replace individual tokens (unknown tokens ignored; values like
  `rgb(r,g,b)` or `ansi:red`). Plugin-shipped themes can't be located from outside the
  CLI → use the `dark` base.

**Values:** the built-in themes' token values are embedded in `colors.py`,
generated at dev time by `scripts/sync_theme.py`, which extracts them from the installed
Claude Code binary and records the CLI version. Re-run it when the CLI changes
its palette (the earlier gold/coral values had already drifted). The `-ansi` themes map
to ANSI named colors (`ansi:green` → SGR 32, etc.), so the terminal's own palette shows through.

**How the CLI treats our escapes (E7):** truecolor, 256-color, named colors, bold, dim and
background colors all pass through unchanged; nothing is dimmed. Two things to know:

- Text with no color of its own is drawn in `inactive` gray (the CLI re-applies it after
  every `ESC[0m`), so anything meant to be `text` white must set it explicitly.
- Without `COLORTERM=truecolor` (and always in Apple Terminal) the CLI downsamples our
  truecolor to the nearest 256-color index itself. dashline always emits truecolor.

**Mapping (settled 11/4):**

| dashline element | Claude Code token | dark value |
|---|---|---|
| model name, cost, project/branch names | `text` (model bold) | `#FFFFFF` |
| effort low / medium / high / xhigh / max | `inactive` / `success` / `warning` / `error` / `error` bold | |
| fast bolt | `fastMode` | `#FF7814` |
| bar ramp anchors | `success` → `warning` → `error` | `#4EBA65` → `#FFC107` → `#FF6B80` |
| bar empty part | `subtle` | `#505050` |
| bar labels and percents | `text` (Phase 2) | |
| separators, plan name, agent, countdowns, stale tag, upstream gone, cwd drift | `inactive` | `#999999` |
| cache expiring, uncommitted/untracked/ahead/behind/never-pushed icons, detached | `warning` | |
| cache cold, limit reached, operations, conflicts, diverged | `error` | |
| `+lines` / `−lines` | `success` / `error` | |

---

## 5. Line 3 — directory row (option C, chosen 11/3)

Goal: the project dir and useful git state, readable at a glance. The draft-2
row had too many numbers. Rules:

- **Icons carry state; numbers appear only where they help.** The only line
  counts are the uncommitted delta. Ahead/behind and conflicts are small counts on
  their icons.
- **Hide what's normal.** A clean, pushed branch shows the folder and branch only.
- **Color = severity:** normal = identity, gold = something to do, coral =
  trouble, dim = background info.
- **Words only for rare, must-see states** (`rebasing 3/7`, `merging`).
- Dropped as redundant or noisy: lines vs default branch, session line churn
  (in a Claude session it mostly duplicates the uncommitted delta), the parent
  path of a repo.

| Situation | Row |
|---|---|
| clean, on main | `󰊢 claude-dashline  󰘬 main` |
| uncommitted | `󰊢 claude-dashline  󰘬 feat/cache  󰏫 +120 −45` |
| + untracked files | `… 󰏫 +120 −45 󰝒` (untracked = icon only, files are never read) |
| only untracked | `… 󰘬 feat/cache  󰝒` |
| unpushed commits | `… 󰘬 feat/cache  󰜷2` |
| behind (as of last fetch) | `… 󰘬 main  󰜮3` |
| diverged | `… 󰜷2 󰜮1` in coral |
| never pushed | `… 󰏫 +30 −2  󰭾` |
| remote branch deleted (PR merged) | `… 󰘬 feat/cache  󱓌` dim |
| detached | `󰊢 claude-dashline  󰜘 a1b2c3d` gold; on a tag `󰓹 v0.1.0` |
| operation in progress | coral: `󱓎 rebasing 3/7`, `󰘭 merging`, `󱁂 cherry-picking`, `󰕌 reverting`, `󰓾 bisecting`, `󰇯 applying patches` |
| conflicts | coral `󰀦 2` (always with a space) |
| linked worktree | `󰊢 claude-dashline 󰙅 wt-cache  󰘬 feat/cache  󰏫 +12` |
| project dir below repo root | `󰊢 monorepo/services/api` (repo name bright, subpath normal) |
| cwd ≠ project dir | `󰊢 claude-dashline  󰘍 tests/fixtures  󰘬 main` dim; path relative to the project when inside it, `~`-collapsed when outside (`󰘍 ~/scratch/repro`) |
| not a git repo | `󰝰 ~/Documents/notes` |

Details:

- A zero side is hidden (`+12`, not `+12 −0`). `+` green, `−` coral, pencil gold.
- Narrow terminals: line counts drop first (the pencil stays), then the cwd drift
  (Phase 4), then the branch truncates with `…` (down to 4 characters), then the
  worktree name; then the row is cut short. Operation, conflicts and sync never drop.
- Built in Phase 4 (11/4): never pushed (`local`) shows only when the repo has a remote;
  during a rebase the row shows the branch being rebased (from `rebase-merge/head-name`),
  not the detached commit; conflict markers count in the uncommitted lines; a repo with
  no commits yet diffs the index against the empty tree. git gets 1 s in total; past
  that, or with no git installed, the row shows the project alone.
- Nerd glyphs (all Material Design `md-`, codepoints checked against
  `glyphnames.json`):

  | Slot | Glyph | Status |
  |---|---|---|
  | git project | 󰊢 md-git F02A2 | chosen (more recognizable than md-source_repository) |
  | plain directory | 󰝰 md-folder_open F0770 | chosen |
  | branch / commit / tag | 󰘬 F062C / 󰜘 F0718 / 󰓹 F04F9 | chosen |
  | ahead / behind | 󰜷 F0737 / 󰜮 F072E | chosen |
  | uncommitted | 󰏫 md-pencil F03EB | chosen |
  | untracked | 󰝒 md-file_plus F0752 | chosen |
  | never pushed | 󰭾 md-cloud_upload_outline F0B7E | chosen |
  | upstream gone | 󱓌 md-source_branch_remove F14CC | chosen |
  | cwd drift | 󰘍 md-subdirectory_arrow_right F060D | chosen |
  | worktree | 󰙅 md-file_tree F0645, replaces the `›`: `󰊢 claude-dashline 󰙅 wt-cache` | chosen |
  | rebasing | 󱓎 md-source_branch_sync F14CE | chosen |
  | merging | 󰘭 md-source_merge F062D | chosen |
  | cherry-picking | 󱁂 md-fruit_cherries F1042 | chosen |
  | reverting | 󰕌 md-undo F054C | chosen |
  | bisecting | 󰓾 md-target F04FE | chosen |
  | applying patches (`git am`) | 󰇯 md-email_open F01EF | chosen (git am applies patches from a mailbox) |
  | conflicts | 󰀦 md-alert F0026, **space before the count** (`󰀦 2`) | chosen |

  Count spacing: conflicts spaced (`󰀦 2`); ahead/behind tight (`󰜷2 󰜮1`).


### Cost

- `git status --porcelain=v2 --branch -z` gives the branch, oid, upstream,
  ahead/behind, per-file states, untracked files and conflicts in one call.
- `git diff --numstat HEAD` only when tracked files are dirty.
- Operation state is read from `.git` files (`rebase-merge/`, `MERGE_HEAD`, …).
  The tag lookup runs only when detached.
- All with `--no-optional-locks`. Budget: 20 ms on a mid-size repo.

**OSC 8 hyperlinks pass through (E3).** The CLI re-emits them with its own `id=` and a BEL
terminator, colors intact, `file://` links included (checked 11/4).

**Links (chosen 11/4: branch and folder):** the project name (or plain folder) links to
`file://<hostname><project dir>`; the branch links to GitHub when it has a live upstream
on a `github.com` / `github.*` remote: `…/compare/<default>...<branch>`, or
`…/tree/<branch>` when it is the default branch (from `refs/remotes/<remote>/HEAD`) or
the default is unknown. Unpushed branches, other hosts, tags and detached commits get no
link. Known limit: over SSH or in a devcontainer the folder link names the remote machine.

---

## 6. Other additions (beyond the original list)

Already folded in above:

- **Plan label from the server**: picks up renames like Max 20x → Ultra without a release.
- **Trial countdown.**
- **Agent name** (`claude --agent X` / `agent` setting runs the main session as a custom agent); self-hiding.
- **"Limit reached" state**: a full bar alone doesn't tell you whether you're blocked.
- **Stale-data age tag**: a failing fetch otherwise looks like zero usage change.
- **Cold-cache cause**: `󰜗 cold (tools changed) 󰑐38k`, from
  `last_miss_cause`. It tells you *why* the next turn costs more.

Considered and left out: session name (`/rename` already sets the terminal title), output style, thinking toggle, vim mode (the CLI shows
it), permission mode (the CLI shows it), session duration, clock.

---

## 7. Glyphs

Three sets, picked with `--glyphs nerd|unicode|ascii` in the statusLine command. All
of them live in one table in `glyphs.py`. Color is independent of the set: `NO_COLOR` turns
color off in any set, and every set still reads without color, since fill and empty
bar characters have different shapes.

Rules for the unicode set: nothing emoji-capable (⚠ ❄ ☁ ⚡ ✖ ✔ ✏ can render two
columns wide) and nothing Nerd Font. The block, box and dot characters `▆ ▁ │ ·` are
"ambiguous width" in Unicode. They're drawn 1 column almost everywhere, and a CJK
terminal set to draw ambiguous characters wide should use `ascii`.

Settled 11/4. Ascii items use ` / `, groups use ` | `:

| Slot | nerd | unicode | ascii |
|---|---|---|---|
| fast mode | 󱐋 | `↯` (the CLI's own) | `fast` |
| cache expiring | `󰔟 3m` | `⧗ 3m` | `cache 3m` |
| cache cold | `󰜗 cold (cause)` | `cache cold (cause)` | `cache cold (cause)` |
| re-cache marker | `󰑐38k` | `↻38k` | `recache 38k` |
| agent | `󱙺 name` | `@name` | `@name` |
| separator, items | ` · ` | ` · ` | ` / ` |
| separator, groups | ` │ ` | ` │ ` | ` \| ` |
| bar fill / empty | `▆` / `▁` | `▆` / `▁` | `#` / `-` |
| git project | `󰊢 name` | `name` | `name` |
| plain directory | `󰝰 path` | `path` | `path` |
| worktree | `name 󰙅 wt` | `name ⑂ wt` | `name [wt]` |
| branch | `󰘬 main` | `⎇ main` | `(main)` |
| detached | `󰜘 a1b2c3d` | `#a1b2c3d` | `(#a1b2c3d)` |
| tag | `󰓹 v0.1.0` | `tag:v0.1.0` | `(tag:v0.1.0)` |
| uncommitted | `󰏫 +120 −45` | `✎ +120 −45` | `* +120 -45` |
| untracked | 󰝒 | `?` | `?` |
| ahead / behind | `󰜷2 󰜮1` | `⇡2 ⇣1` | `>2 <1` (git's own `__git_ps1` symbols) |
| never pushed | 󰭾 | `local` | `local` |
| upstream gone | 󱓌 | `gone` | `gone` |
| operations | per-op icon + word | word only | word only |
| conflicts | `󰀦 2` | `✗ 2` | `! 2` |
| cwd drift | `󰘍 dir` | `↳ dir` | `./dir` inside the project, `~/path` outside it |
| truncation | `…` | `…` | `...` |
| minus sign | `−` | `−` | `-` |

Nerd codepoints are listed in §5 (directory row) and below (line 1). **Default set: `unicode`**
(most people have no Nerd Font). The install skill moves people to `nerd` when it renders,
and helps them get there (§9).

| Line-1 slot | Nerd glyph |
|---|---|
| fast mode | 󱐋 md-lightning_bolt F140B |
| cache expiring | 󰔟 md-timer_sand F051F |
| cache cold | 󰜗 md-snowflake F0717 |
| re-cache marker | 󰑐 md-refresh F0450 |
| agent | 󱙺 md-robot_outline F167A |
| model, effort, plan, cost | no icons (they describe themselves; icons only flag state) |

Bar labels stay text: `context`, `5h`, `7d`, model name (`Fable`), `credits`, `month`.

Notes:

- Ghostty bundles Nerd Font symbols, so `nerd` works here without installing a
  font. Windows Terminal on the work laptop needs a Nerd Font installed.
- Material Design glyphs live in plane 15 (U+F0000+). E4 checks that Claude Code
  measures them as 1 column, as the terminal draws them.

---

## 8. Configuration (settled 11/3)

What would actually need configuring:

1. **Glyph set:** a terminal can't be probed for its font, so this has to be set
   per machine.
2. Hiding elements: nice-to-have.
3. Thresholds (countdown 70%, cache warnings): fine as constants.

**No config file in v1.** The glyph set is a flag in the
`statusLine.command` (`… statusline.py --glyphs nerd`) that the install skill
writes. If hiding elements ever earns its keep, a file goes in
`~/.claude/config/statusline/`.

---

## 9. CLI, skills, plugin

`statusline.py` modes: *(stdin)* render · `--doctor` · `--install [--replace]`
· `--preview [SCENARIO]` · `--glyphs SET` · `--version` · `--help`.

- `--doctor`: one line per check (`ok` / `warn` / `fail` / `info`, a `fix:` line under
  problems), exit 1 on any `fail`. Checks: python, install (installed copy vs the
  running one, by file hash), settings (the winning `statusLine` across managed /
  project-local / project / user, `disableAllHooks`, `refreshInterval`), login (mode,
  label, token source and expiry, never the token), usage (one foreground fetch via
  the same `refresh` the child runs, so it also renews the cache or sets the hold),
  cache (writable, 0700, last fetch, lock), command (runs the settings command through
  `sh -c` on a sample session and times it), git (≥ 2.11), theme, font (Nerd Font
  guess). Phase 6: no profile endpoint any more (§1), and a lock or hold can't wedge
  (a lock expires after 60 s; doctor's fetch replaces the hold), so there is nothing
  to clear by hand.
- `--install [--glyphs SET] [--replace]` (Phase 6, so the skill never edits JSON by
  hand): copies `statusline.py` + `dashline/*.py` + `VERSION` into a sibling folder and
  swaps it in; writes the user `statusLine` through a symlinked settings.json to the
  real file, keeping its mode and key order. Keeps the installed glyph set unless
  `--glyphs` is given, and a dashline entry's own fields (`padding`,
  `refreshInterval`). A statusLine that isn't dashline's is left alone: exit 3 with the
  entry printed, and `--replace` overwrites it. Notes a project statusLine that wins.
- `--glyphs all` (preview only) prints each set in turn, for the install skill.
- `--preview [SCENARIO|all]`: built-in scenarios with fake data at a fixed clock:
  `pro-trial`, `pro`, `ultra-fable`, `team`, `enterprise`, `api`, `limit`, `rebase`,
  `narrow` (80 columns: `credits` moves up), `tiny` (64 columns: text-only bars). Uses
  the active theme and `NO_COLOR`; reads no account, network or git. The README SVG
  and the install skill both use it. (Phase 5: `free-trial` became `pro-trial`, since
  the trial is a Pro trial; `limit` and `tiny` added.)

Skills (model-invocable, so a plain-language request like "fix my statusline" triggers them):

- `install`: check python ≥ 3.9 (macOS: Homebrew first, else command-line tools), copy the
  package, write the settings entry, run `--doctor`. Glyph setup:
  1. **Guess:** Ghostty and WezTerm bundle Nerd Font symbols (`$TERM_PROGRAM`);
     otherwise look for an installed Nerd Font (`fc-list` on Linux, font dirs on macOS).
     Kitty and others: verify before claiming.
  2. **Show:** print `--preview` in all three sets and ask which renders correctly.
     That's the real test, since a font can be installed but not selected.
  3. **Suggest, don't install** (settled 11/4) when nerd doesn't render: print a short note
     on what a Nerd Font adds, a link to the Symbols Nerd Font ("Symbols Only"), and the
     one-line install for the OS (Linux: `~/.local/share/fonts` + `fc-cache`; macOS:
     `brew install --cask font-symbols-only-nerd-font`; Windows Terminal: pick a Nerd Font
     as the face). The skill never installs fonts or edits terminal config.
  4. Re-running `install` after setting up a font re-previews and switches to `--glyphs nerd`.
  Default without any of this: `unicode`. If settings.json already has a `statusLine`
  entry, show it and ask before replacing it.
- `doctor`: run `--doctor`, explain each line, fix what's safe (re-copy
  stale install, re-point settings, clear a wedged lock/hold).


---

## 10. README preview

`scripts/preview.py`: `--preview` per scenario → ANSI → SVG. Starts from the
author's earlier ANSI→SVG renderer approach (bar cells as rects, text runs pinned with
`textLength`), free to change. **The preview shows the `nerd` set** (settled 11/4),
so the SVG embeds a subset of Symbols Nerd Font (MIT; keep its license notice) for
just the glyphs used. Output `docs/preview.svg`. CI fails if regenerating it changes
anything. Check by eye with headless Chrome `--screenshot`.

---

## 11. Repo layout

```
.claude-plugin/plugin.json
skills/install/SKILL.md
skills/doctor/SKILL.md
src/dashline/
  __init__.py  __main__.py
  stdin.py      Claude Code JSON → dataclass
  account.py    auth mode, plan label (.claude.json), token (file + macOS Keychain)
  usage.py      usage fetch, cache, lock, hold, background refresh
  bars.py       bar cells, ramp color, countdown
  layout.py     lines 1–2: widths, overflow to line 1, text-only fallback, drop order
  repo.py       directory row
  glyphs.py     nerd / unicode / ascii
  theme.py      which Claude Code theme is active; tokens → SGR
  colors.py     theme tokens, generated by scripts/sync_theme.py
  doctor.py  install.py  preview.py
statusline.py   entry shim (what gets copied)
scripts/preview.py
tests/  fixtures/{stdin,usage,profile}/*.json
docs/PLAN.md  docs/preview.svg
pyproject.toml  README.md  CHANGELOG.md  LICENSE (MIT)  CLAUDE.md
```

Tests: pure functions take `now` and `columns` as arguments (no libfaketime); git
tests build throwaway repos in `tmp_path`; fetch tests hit a local
`http.server`; golden tests compare full rendered lines per scenario; one
fixture set per plan (the old plan→bar table becomes these expectations).

---

## 12. Phases

**Phase 0 — verify** (scratch scripts, nothing committed):

| # | Question | How |
|---|---|---|
| E1 | Does `cost.total_cost_usd` include subagents? | session that spawns one; dump stdin before/after; compare `/cost` |
| E2 | Does `refreshInterval` fire while idle? With several sessions, does the shared cache/lock hold? | log invocations |
| E3 | Do OSC 8 links pass through? | test statusline |
| E4 | Nerd glyph widths in Claude Code vs the terminal | ruler line |
| E5 | Frame reserve columns in 2.1.318 (was 5) | fill-to-width line |
| E6 | Fixtures: Free, Pro, Max 5x, Team, Enterprise usage + profile | Enterprise from the work laptop (scrubbed); the rest synthesized from the schema unless someone can capture |
| E7 | Does Claude Code pass truecolor, 256-color and ANSI named colors through the statusline unchanged, or dim them? | test statusline printing each |
| E8 | Theme: confirm `~/.claude.json` `theme` is read live; how `auto`, custom themes and overrides are stored/resolved | change theme in `/config`, watch the file; read binary |

**Phase 0 results (11/4, CLI 2.1.318, pty harness, `--setting-sources project --settings`):**

| # | Result |
|---|---|
| E1 | **yes, includes subagents.** `claude -p --output-format json` with a Haiku subagent under Sonnet: `total_cost_usd` 0.0430 = Sonnet 0.0414 + Haiku 0.0016, and the statusline reads the same ledger. A background subagent's cost lands as it runs, so the next refresh shows it |
| E2 | idle refresh: **yes**, every 2.05 s at `refreshInterval: 2`, one call at startup. Multi-session cache/lock is our own code, tested in Phase 3 |
| E3 | **passes through** (re-emitted with `id=` + BEL) (§5) |
| E4 | the CLI counts Nerd PUA (plane 15), the ambiguous-width set (`▆▁│·↑↓`) and the unicode fallbacks as **1 column** each. Ghostty agrees: a 40-cell ruler of every glyph lines up, icons unclipped even packed tight |
| E5 | reserve **4** (§4) |
| E6 | Captured via `scripts/capture_fixtures.py` into `tests/fixtures/{usage,profile}/`: `ultra` (credits on), `ultra-credits-off`, `enterprise` (no `plan_display_name`; empty `limits[]`; monthly `spend` cap; limit amount replaced with a placeholder). Free, Pro, Max 5x, Team synthesized |
| E7 | **unchanged**, no dimming; uncolored text = `inactive`; downsampled to 256 without `COLORTERM` (§4a) |
| E8 | theme lives in settings files (legacy `~/.claude.json`), `auto` = OSC 11 → `COLORFGBG` → dark, custom = `themes/<slug>.json` (§4a) |

Also seen on stdin before the first API response: `output_style`, `thinking`,
`exceeds_200k_tokens`, `scratchpad_dir`; `rate_limits` and `prompt_cache` are absent until
the first response, so every field is optional.

**Phase 1** skeleton: pyproject/uv/ruff/pytest/CI, plugin.json, package stubs,
shim, CLAUDE.md (Co-Authored-By, no session trailer).
**Phase 2** lines 1–2 (layout E3, bars, overflow) from stdin only (context, 5h, 7d),
with the glyph table from the start (all three sets).
**Phase 3** account + usage: plan label, fetch/cache, data-driven rows,
credits, month, limit-reached, stale tag. Done 11/4: the label comes from the CLI's
own cached profile in `.claude.json`, so there is no profile fetch and no
`profile.json` (§1).
**Phase 4** directory row. Done 11/4, with branch and folder links (§5).
**Phase 5** glyph polish: `--preview` in each set, NO_COLOR, ambiguous-width checks.
Done 11/4: `tests/test_glyphs.py` checks every glyph and every character a preview
prints: no East Asian Wide/Fullwidth, no combining or format characters, nothing with
the Unicode Emoji property, no private-use characters in `unicode`, pure ASCII in
`ascii`, Nerd icons only from the Material Design range.
**Phase 6** `--doctor`, `--preview`, install + doctor skills. Done 11/4: `--install`
added (§9). The install skill asks the user to run the `--glyphs all` preview with `!`,
since only their own command's output is sure to show in their terminal's font. Checked
in the pty harness: Claude Code doesn't wait for the detached child. With
`refreshInterval: 2`, a statusline that left a 30 s detached child each run still
refreshed every 2.0 s.
**Phase 7** README + preview, 0.1.0, GitHub; claude-toolbox listing when ready.
11/4: README, `docs/preview.svg` (hero: `ultra-fable`) and `docs/plans.svg` (gallery: pro,
team, enterprise, api, limit, rebase, with captions), drawn at 100 columns in the dark
theme. The icon font is a 5 KB subset of Symbols Nerd Font Mono v3.5.1 covering every
icon in the nerd set, committed in `scripts/assets/` with the MIT (Nerd Fonts) and
Apache 2.0 (Material Design Icons) licenses; fontTools is a dev dependency, used only to
rebuild it. CI job `preview` runs `scripts/preview.py --check`. Version 0.1.0.

**Later:** pace tick. (Retiring the earlier plugins is the author's own housekeeping,
outside this repo. The compaction-point work does **not** move here.)

---

## 13. Open questions

None on design as of 11/4: layout, bars, colors, icons, separators and glyph sets are
settled. Next: commit this plan, then Phase 0 (E1–E8), then the build.
