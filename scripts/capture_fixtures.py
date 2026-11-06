"""Capture this account's usage + profile responses as scrubbed test fixtures.

Usage: python3 capture_fixtures.py PLAN      (PLAN: free, pro, max5x, ultra, team, enterprise)

Reads the Claude Code OAuth token the way the statusline does (CLAUDE_CODE_OAUTH_TOKEN,
the macOS Keychain, or the credentials file), calls
/api/oauth/usage and /api/oauth/profile once each through the statusline's own request
(which refuses redirects, so the token only goes to api.anthropic.com), removes names,
emails, ids (every `id`, `uuid`, `*_id` and `*_uuid` value, and anything UUID-shaped)
and URLs, and writes fixture-PLAN.json in the current directory. The token stays in this
process. Read the output before sharing it; anything personal left in it is a bug here.
An error answer is kept as its status alone: the statusline's request drops error bodies.
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
# Free-text fields that name a person or an organization.
PERSONAL = {
    "full_name",
    "display_name",
    "name",
    "email",
    "email_address",
    "created_at",
    "subscription_created_at",
}
KEEP_UNDER = {"model", "rows", "application"}  # names and ids here are product names
PLACEHOLDER = "00000000-0000-4000-8000-000000000000"


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


def scrub(o, parent=""):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in PERSONAL and isinstance(v, str) and parent not in KEEP_UNDER:
                out[k] = f"<{k}>"
            elif is_id(k) and v not in (None, "") and parent not in KEEP_UNDER:
                if isinstance(v, (dict, list)):
                    out[k] = scrub(v, k)
                elif isinstance(v, str) and UUID.fullmatch(v):
                    out[k] = PLACEHOLDER
                else:
                    out[k] = f"<{k}>"
            else:
                out[k] = scrub(v, k)
        return out
    if isinstance(o, list):
        return [scrub(v, parent) for v in o]
    if isinstance(o, str):
        o = EMAIL.sub("<email>", o)
        o = UUID.sub(PLACEHOLDER, o)
        return URL.sub("https://example.invalid/", o)
    return o


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
    print(f"wrote {out}. Every string left in it, for review:")
    seen = set()

    def strings(o):
        if isinstance(o, dict):
            for v in o.values():
                strings(v)
        elif isinstance(o, list):
            for v in o:
                strings(v)
        elif isinstance(o, str) and o not in seen:
            seen.add(o)
            print("  ", o)

    strings(data)


if __name__ == "__main__":
    main()
