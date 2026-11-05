"""Capture this account's usage + profile responses as scrubbed test fixtures.

Usage: python3 capture_fixtures.py PLAN      (PLAN: free, pro, max5x, ultra, team, enterprise)

Reads the Claude Code OAuth token (credentials file, or the macOS Keychain), calls
/api/oauth/usage and /api/oauth/profile once each, removes names, emails, ids and URLs,
and writes fixture-PLAN.json in the current directory. The token stays in this process.
Read the output before sharing it; anything personal left in it is a bug here.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

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
KEEP_UNDER = {"model", "rows", "application"}  # display names here are product names


def token():
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    path = config / ".credentials.json"
    if path.exists():
        return json.loads(path.read_text())["claudeAiOauth"]["accessToken"]
    if sys.platform == "darwin":
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return json.loads(out)["claudeAiOauth"]["accessToken"]
    sys.exit("no Claude Code credentials found; log in with /login first")


def get(path, tok):
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bearer {tok}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "dashline-capture",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"status": r.status, "body": json.load(r)}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        with contextlib.suppress(ValueError):
            body = json.loads(body)
        return {"status": e.code, "body": body}


def scrub(o, parent=""):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k in PERSONAL and isinstance(v, str) and parent not in KEEP_UNDER:
                out[k] = f"<{k}>"
            elif k == "uuid" or k.endswith("_uuid"):
                out[k] = "00000000-0000-4000-8000-000000000000" if v else v
            else:
                out[k] = scrub(v, k)
        return out
    if isinstance(o, list):
        return [scrub(v, parent) for v in o]
    if isinstance(o, str):
        o = EMAIL.sub("<email>", o)
        o = UUID.sub("00000000-0000-4000-8000-000000000000", o)
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
