"""Who is signed in: subscription or API, the plan label, and the OAuth token (PLAN §1).

The label comes from what Claude Code already caches in `.claude.json` (`oauthAccount`,
refreshed by the CLI from /api/oauth/profile), so a render reads one local file and never
calls the profile endpoint. The token is read only by the background fetch, never by a
render, and never leaves the process.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

from dashline.stdin import _num, iso_time
from dashline.theme import config_dir

# Third-party providers: no plan, no usage endpoint.
PROVIDERS = (
    ("CLAUDE_CODE_USE_BEDROCK", "Bedrock"),
    ("CLAUDE_CODE_USE_VERTEX", "Vertex"),
    ("CLAUDE_CODE_USE_FOUNDRY", "Foundry"),
    ("CLAUDE_CODE_USE_ANTHROPIC_AWS", "API"),
    ("CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD", "API"),
    ("CLAUDE_CODE_USE_MANTLE", "API"),
)
# organization_type → label, when the profile has no plan_display_name (Enterprise doesn't).
ORG_TYPES = {
    "claude_enterprise": "Enterprise",
    "claude_team": "Team",
    "claude_pro": "Pro",
    "claude_max": "Max",
}
# credentials subscriptionType → label, the last resort.
SUBSCRIPTIONS = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise"}
TEAM_TYPES = ("claude_team", "claude_enterprise")
EXPIRY_MARGIN = 60  # seconds: a token this close to expiry counts as expired


def _truthy(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on")


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def claude_json_path(env) -> str:
    return os.path.join(env.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~"), ".claude.json")


def credentials_path(env) -> str:
    return os.path.join(config_dir(env), ".credentials.json")


def _tier_label(base: str, tier) -> str:
    """Max on the 20x rate tier is sold as Ultra."""
    if base == "Max" and isinstance(tier, str) and "20x" in tier:
        return "Ultra"
    return base


class Account:
    """mode: "subscription" (fetch usage) or "api" (no plan bars)."""

    def __init__(self, mode: str, label: str | None = None, **info):
        self.mode = mode
        self.label = label
        self.org_type = info.get("org_type")
        self.trial_ends_at = info.get("trial_ends_at")
        self.fingerprint = info.get("fingerprint")

    @property
    def team(self) -> bool:
        """Team and Enterprise spend is a monthly cap, not pay-as-you-go credits."""
        return self.org_type in TEAM_TYPES


def _api_key_approved(key: str, claude_json: dict) -> bool:
    """The CLI uses ANTHROPIC_API_KEY once the user approves it; it stores the last 20 chars."""
    approved = (claude_json.get("customApiKeyResponses") or {}).get("approved")
    return isinstance(approved, list) and key[-20:] in approved


def load(env, session=None) -> Account:
    """How this session is billed, and the plan label to show."""
    for var, label in PROVIDERS:
        if _truthy(env.get(var)):
            return Account("api", label)
    if session is not None and session.spend_limit is not None:
        return Account("api", "Gateway")

    claude_json = _read_json(claude_json_path(env))
    oauth = claude_json.get("oauthAccount")
    oauth = oauth if isinstance(oauth, dict) else {}
    windows = session is not None and bool(session.windows)
    env_token = bool(env.get("CLAUDE_CODE_OAUTH_TOKEN"))
    # Plan windows on stdin settle it: the CLI only sends them to subscribers.
    if not windows:
        key = env.get("ANTHROPIC_API_KEY") or ""
        if env.get("ANTHROPIC_AUTH_TOKEN") or (key and _api_key_approved(key, claude_json)):
            return Account("api", "API")
        if not oauth and not env_token:
            return Account("api", "API")

    org_type = oauth.get("organizationType")
    return Account(
        "subscription",
        plan_label(oauth, env),
        org_type=org_type if isinstance(org_type, str) else None,
        trial_ends_at=iso_time(oauth.get("claudeCodeTrialEndsAt")),
        fingerprint=fingerprint(oauth, env),
    )


def fingerprint(oauth: dict, env) -> str | None:
    """Which login the cached usage belongs to: a hash of the account and org ids."""
    ids = (oauth.get("accountUuid"), oauth.get("organizationUuid"))
    if all(isinstance(x, str) and x for x in ids):
        return hashlib.sha256(":".join(ids).encode()).hexdigest()[:16]
    return "env" if env.get("CLAUDE_CODE_OAUTH_TOKEN") else None


def identity(env) -> str | None:
    """The current login's fingerprint, read the way load() reads it."""
    oauth = _read_json(claude_json_path(env)).get("oauthAccount")
    return fingerprint(oauth if isinstance(oauth, dict) else {}, env)


def plan_label(oauth: dict, env) -> str | None:
    """plan_display_name → organization type → the credentials' subscription type."""
    name = oauth.get("planDisplayName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    org = ORG_TYPES.get(oauth.get("organizationType"))
    if org:
        return _tier_label(org, oauth.get("organizationRateLimitTier"))
    creds = _read_json(credentials_path(env)).get("claudeAiOauth")
    if isinstance(creds, dict):
        sub = SUBSCRIPTIONS.get(creds.get("subscriptionType"))
        if sub:
            return _tier_label(sub, creds.get("rateLimitTier"))
    return None


def trial_text(account: Account, now: float) -> str | None:
    """`trial 5d` while a Claude Code trial runs, `trial 7h` on its last day."""
    if account.trial_ends_at is None or account.trial_ends_at <= now:
        return None
    left = account.trial_ends_at - now
    if left >= 86400:
        return f"trial {-(-int(left) // 86400)}d"
    return f"trial {max(1, -(-int(left) // 3600))}h"


def label_text(account: Account, glyphs: dict, now: float) -> str | None:
    """The plan name as shown, with the trial countdown appended."""
    trial = trial_text(account, now)
    if account.label and trial:
        return f"{account.label}{glyphs['sep_item']}{trial}"
    return account.label or trial


# ---- the token (background fetch only) ----


def keychain_service(env) -> str:
    """The CLI's Keychain item: a per-directory suffix when CLAUDE_CONFIG_DIR is set."""
    import unicodedata

    custom = env.get("CLAUDE_CONFIG_DIR")
    if not custom:
        return "Claude Code-credentials"
    digest = hashlib.sha256(unicodedata.normalize("NFC", custom).encode()).hexdigest()[:8]
    return f"Claude Code-credentials-{digest}"


def keychain_account(env) -> str:
    user = env.get("USER") or ""
    ok = user and all(c.isalnum() or c in "._-" for c in user) and user.isascii()
    return user if ok else "claude-code-user"


def _read_keychain(env) -> dict:
    """The credentials JSON from the macOS Keychain, or {}."""
    import subprocess

    try:
        r = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                keychain_account(env),
                "-w",
                "-s",
                keychain_service(env),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if r.returncode != 0:
        return {}
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def find_token(env, now: float, platform: str | None = None) -> tuple:
    """(token, source, expires_at) or (None, why, None).

    The env token first, then the Keychain (macOS), then the file. `source` names where
    the token came from, for doctor; `expires_at` is in seconds, or None if unknown.
    """
    token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        return token, "CLAUDE_CODE_OAUTH_TOKEN", None
    platform = platform or sys.platform
    sources = []
    if platform == "darwin":
        sources.append(("macOS Keychain", lambda: _read_keychain(env)))
    sources.append((credentials_path(env), lambda: _read_json(credentials_path(env))))
    for source, read in sources:
        oauth = read().get("claudeAiOauth")
        if not isinstance(oauth, dict):
            continue
        token = oauth.get("accessToken")
        if not isinstance(token, str) or not token:
            continue
        expires = _num(oauth.get("expiresAt"))
        expires = expires / 1000 if expires is not None else None
        if expires is not None and expires < now + EXPIRY_MARGIN:
            return None, "token expired (Claude Code renews it on its next request)", expires
        return token, source, expires
    return None, "no Claude login found", None


def read_token(env, now: float, platform: str | None = None) -> tuple:
    """(token, None) or (None, why)."""
    token, why, _ = find_token(env, now, platform)
    return (token, None) if token else (None, why)
