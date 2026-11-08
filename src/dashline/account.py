"""Who is signed in: subscription or API, the plan label, and the OAuth token (PLAN §1).

The label comes from what Claude Code already caches in `.claude.json` (`oauthAccount`,
refreshed by the CLI from /api/oauth/profile), so a render never calls the profile
endpoint. When that has no plan, a render falls back to the credentials file's
`subscriptionType`, but it never takes the token from it: only the background fetch and
doctor do (`find_token`). A `CLAUDE_CODE_OAUTH_TOKEN` is in a render's environment
anyway; a hash of it tags the cache, since it may belong to another login than
`.claude.json`. The token itself is only ever sent to api.anthropic.com.
"""

from __future__ import annotations

import json
import os
import sys

from dashline.stdin import _num, iso_time
from dashline.text import clean, cut
from dashline.theme import _read_json, config_dir, home_dir

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
MAX_PLAN = 20  # columns of the plan name, as for bar labels (usage.MAX_LABEL)


def _truthy(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on")


def claude_json_path(env) -> str:
    """`.claude.json`: in CLAUDE_CONFIG_DIR, else in HOME (`env`'s, not the process's)."""
    return os.path.join(env.get("CLAUDE_CONFIG_DIR") or home_dir(env), ".claude.json")


def read_claude_json(env) -> dict:
    """`.claude.json` as a dict. It grows with project history, so a render reads it
    once and hands it to load() and the theme."""
    return _read_json(claude_json_path(env))


def credentials_path(env) -> str:
    return os.path.join(config_dir(env), ".credentials.json")


def _key(value) -> str | None:
    """A string to look up in a table, or None: an odd JSON type can't be a dict key."""
    return value if isinstance(value, str) else None


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
        # An older .claude.json may name the plan without the organization's type.
        return self.org_type in TEAM_TYPES or self.label in ("Team", "Enterprise")


def _api_key_approved(key: str, claude_json: dict) -> bool:
    """The CLI uses ANTHROPIC_API_KEY once the user approves it; it stores the last 20 chars."""
    responses = claude_json.get("customApiKeyResponses")
    approved = responses.get("approved") if isinstance(responses, dict) else None
    return isinstance(approved, list) and key[-20:] in approved


def load(env, session=None, claude_json: dict | None = None) -> Account:
    """How this session is billed, and the plan label to show. claude_json: as
    read_claude_json() returns it, when the caller has it already."""
    for var, label in PROVIDERS:
        if _truthy(env.get(var)):
            return Account("api", label)
    if session is not None and session.spend_limit is not None:
        return Account("api", "Gateway")

    if claude_json is None:
        claude_json = read_claude_json(env)
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
    """Which login the cached usage belongs to: a hash of the account and org ids, or
    of the email when they're missing.

    A `CLAUDE_CODE_OAUTH_TOKEN` wins over the stored login (the fetch uses it), and it
    may be another account's, so its own hash tags the cache instead. 64 bits of a
    salted SHA-256 can't be turned back into the token.
    """
    import hashlib

    token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        digest = hashlib.sha256(b"dashline-cache-tag:" + token.encode("utf-8", "replace"))
        return "env-" + digest.hexdigest()[:16]
    ids = (oauth.get("accountUuid"), oauth.get("organizationUuid"))
    if all(isinstance(x, str) and x for x in ids):
        return hashlib.sha256(":".join(ids).encode("utf-8", "replace")).hexdigest()[:16]
    # Without the ids, the email still tells two logins apart (or they'd share a cache).
    email = oauth.get("emailAddress")
    if isinstance(email, str) and email.strip():
        tagged = b"dashline-email:" + email.strip().lower().encode("utf-8", "replace")
        return hashlib.sha256(tagged).hexdigest()[:16]
    return None


def identity(env) -> str | None:
    """The current login's fingerprint, read the way load() reads it."""
    oauth = _read_json(claude_json_path(env)).get("oauthAccount")
    return fingerprint(oauth if isinstance(oauth, dict) else {}, env)


def plan_label(oauth: dict, env) -> str | None:
    """plan_display_name → organization type → the credentials' subscription type."""
    name = oauth.get("planDisplayName")
    if isinstance(name, str) and name.strip():
        # Cut as the bar labels are (usage.MAX_LABEL): a long one would push every
        # plan bar off line 2.
        return cut(clean(name.strip()), MAX_PLAN).strip() or None
    org = ORG_TYPES.get(_key(oauth.get("organizationType")))
    if org:
        return _tier_label(org, oauth.get("organizationRateLimitTier"))
    creds = _read_json(credentials_path(env)).get("claudeAiOauth")
    if isinstance(creds, dict):
        sub = SUBSCRIPTIONS.get(_key(creds.get("subscriptionType")))
        if sub:
            return _tier_label(sub, creds.get("rateLimitTier"))
    return None


def trial_text(account: Account, now: float) -> str | None:
    """`trial 5d` while a Claude Code trial runs, `trial 7h` on its last day."""
    from dashline.bars import DAYS_MAX

    if account.trial_ends_at is None or account.trial_ends_at <= now:
        return None
    left = account.trial_ends_at - now
    if left >= 86400:
        return f"trial {min(-(-int(left) // 86400), DAYS_MAX)}d"  # 999d at most
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
    import hashlib
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


class KeychainError(Exception):
    """The Keychain has the item but wouldn't hand it over: locked, or access denied."""


KEYCHAIN_LOCKED = "the macOS Keychain is locked or denied access"
KEYCHAIN_NOT_FOUND = 44  # `security`'s exit code for errSecItemNotFound
# Seconds `security` gets: macOS may first ask the user to allow access. The background
# fetch can't wait long (its lock goes stale after 60 s); doctor, which the user is
# watching, gives them time to answer.
KEYCHAIN_WAIT = 5
KEYCHAIN_WAIT_ASKED = 60


def _read_keychain(env, wait: float = KEYCHAIN_WAIT) -> dict:
    """The credentials JSON from the macOS Keychain, or {} if there is none.

    Raises KeychainError when `security` fails for another reason, such as a locked
    Keychain over SSH ("User interaction is not allowed"), a denied prompt, or one left
    waiting: /login can't fix those, so they mustn't read as "no login".
    """
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
            timeout=wait,
        )
    except subprocess.TimeoutExpired:
        raise KeychainError(KEYCHAIN_LOCKED) from None  # a prompt nobody answered
    except (OSError, subprocess.SubprocessError):
        return {}  # no `security`: not a Mac after all
    if r.returncode == KEYCHAIN_NOT_FOUND:
        return {}
    if r.returncode != 0:
        raise KeychainError(KEYCHAIN_LOCKED)
    try:
        data = json.loads(r.stdout)
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


# A token an HTTP header can't carry (a stray line ending from a file saved on Windows,
# a space): the request would fail before it's sent, which reads like a network fault.
BAD_ENV_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN has a character a request can't carry"
BAD_STORED_TOKEN = "the stored token has a character a request can't carry"


def _sendable(token: str) -> bool:
    """Printable ASCII without spaces: what a bearer token is made of."""
    return token.isascii() and token.isprintable() and " " not in token


def find_token(
    env, now: float, platform: str | None = None, keychain_wait: float = KEYCHAIN_WAIT
) -> tuple:
    """(token, source, expires_at) or (None, why, None).

    The env token first, then the Keychain (macOS), then the file. `source` names where
    the token came from, for doctor; `expires_at` is in seconds, or None if unknown.
    keychain_wait: how long a Keychain prompt may wait for the user (KEYCHAIN_WAIT).
    """
    token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        if not _sendable(token):
            return None, BAD_ENV_TOKEN, None
        return token, "CLAUDE_CODE_OAUTH_TOKEN", None
    platform = platform or sys.platform
    sources = []
    if platform == "darwin":
        sources.append(("macOS Keychain", lambda: _read_keychain(env, keychain_wait)))
    sources.append((credentials_path(env), lambda: _read_json(credentials_path(env))))
    locked = None
    for source, read in sources:
        try:
            oauth = read().get("claudeAiOauth")
        except KeychainError as e:
            locked = str(e)  # the file may still have a token
            continue
        if not isinstance(oauth, dict):
            continue
        token = oauth.get("accessToken")
        if not isinstance(token, str) or not token:
            continue
        expires = _num(oauth.get("expiresAt"))
        expires = expires / 1000 if expires is not None else None
        if expires is not None and expires < now + EXPIRY_MARGIN:
            return None, "token expired (Claude Code renews it on its next request)", expires
        if not _sendable(token):
            return None, BAD_STORED_TOKEN, expires
        return token, source, expires
    return None, locked or "no Claude login found", None


def read_token(env, now: float, platform: str | None = None) -> tuple:
    """(token, None) or (None, why)."""
    token, why, _ = find_token(env, now, platform)
    return (token, None) if token else (None, why)
