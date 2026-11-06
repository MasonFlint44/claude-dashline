"""Capture this account's usage + profile responses as scrubbed test fixtures.

Usage: python3 capture_fixtures.py PLAN      (PLAN: free, pro, max5x, ultra, team, enterprise)

Reads the Claude Code OAuth token the way the statusline does (CLAUDE_CODE_OAUTH_TOKEN,
the macOS Keychain, or the credentials file), calls
/api/oauth/usage and /api/oauth/profile once each through the statusline's own request
(which refuses redirects, so the token only goes to api.anthropic.com), scrubs the
answers and writes fixture-PLAN.json in the current directory. The token stays in this
process. An error answer is kept as its status alone: the statusline's request drops
error bodies.

Scrubbing keeps a string only under a key known to hold product vocabulary (a limit's
`kind`, `severity`, a plan name, a reset time, …); every other string becomes `<key>`,
and a UUID-shaped id the zero UUID. So a field the server adds later (a name, an email,
a domain) is scrubbed by default. Under `model`, an `id` stays only if it looks like a
model id (`claude-…`). Even kept strings lose emails, UUIDs and URLs. Numbers are kept,
since the tests need real percents and caps; money amounts are listed with the strings
for review, so a real spend cap can be swapped for a placeholder by hand. Read the
output before sharing it; anything personal left in it is a bug here.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

API = "https://api.anthropic.com"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
EMAIL = re.compile(r"[^\s\"@]+@[^\s\"@]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://[^\s)\"'<>]+")
MODEL_ID = re.compile(r"claude-[a-z0-9][a-z0-9.\-]*")
# Keys whose string values are product vocabulary, kept wherever they appear.
KEEP = {
    # limits and windows
    "kind",
    "group",
    "severity",
    "surface",
    "locked_reason",
    "disabled_reason",
    "currency",
    "disclaimer",
    "key",
    # times the statusline reads
    "resets_at",
    "as_of",
    "window_started_at",
    "claude_code_trial_ends_at",
    # plan
    "organization_type",
    "billing_type",
    "rate_limit_tier",
    "seat_tier",
    "subscription_status",
    "plan_display_name",
    "plan_display_label",
}
# More keys kept under one parent: product and model names there aren't personal.
KEEP_UNDER = {
    "application": {"name", "slug"},
    "model": {"display_name"},
    "rows": {"display_name"},
}
PLACEHOLDER = "00000000-0000-4000-8000-000000000000"
# A number under a key with one of these words is money (or a cap): listed for review.
MONEY = ("dollar", "credit", "amount", "limit", "spend", "cost", "price", "balance")


def token():
    """The token the statusline would use: the same lookup, so the Keychain item for a
    CLAUDE_CONFIG_DIR and the env token are found too."""
    import time

    from dashline import account

    tok, why = account.read_token(os.environ, time.time())
    if tok is None:
        sys.exit(f"no usable Claude Code login ({why}); log in with /login first")
    return tok


def get(path, tok):
    from dashline import usage

    status, data, _retry = usage.get(API + path, tok, timeout=15)
    return {"status": status, "body": data}


def is_id(key):
    return key in ("id", "uuid") or key.endswith(("_id", "_uuid"))


def clean(text):
    text = EMAIL.sub("<email>", text)
    text = UUID.sub(PLACEHOLDER, text)
    return URL.sub("https://example.invalid/", text)


def scrub(o, key="", parent=""):
    """`o` with every string not known to be safe replaced. `key` is the key `o` sits
    under (a list's items share it), `parent` the key of the object holding it."""
    if isinstance(o, dict):
        return {k: scrub(v, k, key) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v, key, parent) for v in o]
    if not isinstance(o, str) or o == "":
        return o
    if key == "id" and parent == "model" and MODEL_ID.fullmatch(o):
        return o
    if key in KEEP or key in KEEP_UNDER.get(parent, ()):
        return clean(o)
    if is_id(key) and UUID.fullmatch(o):
        return PLACEHOLDER
    return f"<{key}>" if key else "<value>"


def review(data):
    """Print every string and every money amount left in `data`, once each."""
    seen = set()

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str) and o not in seen:
            seen.add(o)
            print("  ", o)
        elif (
            isinstance(o, (int, float))
            and not isinstance(o, bool)
            and any(word in key.lower() for word in MONEY)
            and (key, o) not in seen
        ):
            seen.add((key, o))
            print(f"   {key} = {o}   (money: replace a real cap with a placeholder)")

    walk(data)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    plan = sys.argv[1]
    tok = token()
    data = {
        "plan": plan,
        "usage": scrub(get("/api/oauth/usage", tok)),
        "profile": scrub(get("/api/oauth/profile", tok)),
    }
    out = f"fixture-{plan}.json"
    Path(out).write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {out}. Every string and money amount left in it, for review:")
    review(data)


if __name__ == "__main__":
    main()
