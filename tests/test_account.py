"""Auth mode, plan label, trial and token reading (account.py)."""

import hashlib
import json

import pytest

from conftest import NOW, make_session
from dashline import account, glyphs

ULTRA = {
    "accountUuid": "11111111-1111-4111-8111-111111111111",
    "organizationUuid": "22222222-2222-4222-8222-222222222222",
    "organizationType": "claude_max",
    "organizationRateLimitTier": "default_claude_max_20x",
    "planDisplayName": "Ultra",
    "claudeCodeTrialEndsAt": None,
}
ENTERPRISE = {
    "accountUuid": "33333333-3333-4333-8333-333333333333",
    "organizationUuid": "44444444-4444-4444-8444-444444444444",
    "organizationType": "claude_enterprise",
    "organizationRateLimitTier": "default_claude_zero",
    "seatTier": "enterprise_usage_based",
}


def write_claude_json(home, oauth=None, **extra):
    data = dict(extra)
    if oauth is not None:
        data["oauthAccount"] = oauth
    (home / ".claude.json").write_text(json.dumps(data))


def write_credentials(home, **oauth):
    conf = home / ".claude"
    conf.mkdir(exist_ok=True)
    (conf / ".credentials.json").write_text(json.dumps({"claudeAiOauth": oauth}))


def env_for(home, **extra):
    return {"HOME": str(home), **extra}


# ---- mode ----


@pytest.mark.parametrize(
    ("var", "label"),
    [
        ("CLAUDE_CODE_USE_BEDROCK", "Bedrock"),
        ("CLAUDE_CODE_USE_VERTEX", "Vertex"),
        ("CLAUDE_CODE_USE_FOUNDRY", "Foundry"),
        ("CLAUDE_CODE_USE_MANTLE", "API"),
    ],
)
def test_providers_are_api(isolated_home, var, label):
    write_claude_json(isolated_home, ULTRA)
    acct = account.load(env_for(isolated_home, **{var: "1"}), make_session())
    assert (acct.mode, acct.label) == ("api", label)


def test_provider_flag_must_be_truthy(isolated_home):
    write_claude_json(isolated_home, ULTRA)
    acct = account.load(env_for(isolated_home, CLAUDE_CODE_USE_BEDROCK="0"), make_session())
    assert acct.mode == "subscription"


def test_gateway_spend_limit_is_api(isolated_home):
    write_claude_json(isolated_home, ULTRA)
    session = make_session(rate_limits={"spend_limit": {"used_percentage": 12}})
    acct = account.load(env_for(isolated_home), session)
    assert (acct.mode, acct.label) == ("api", "Gateway")


def test_subscription_from_oauth_account(isolated_home):
    write_claude_json(isolated_home, ULTRA)
    acct = account.load(env_for(isolated_home), make_session("startup"))
    assert (acct.mode, acct.label, acct.org_type) == ("subscription", "Ultra", "claude_max")
    assert not acct.team


def test_no_login_is_api(isolated_home):
    acct = account.load(env_for(isolated_home), make_session("startup"))
    assert (acct.mode, acct.label) == ("api", "API")


def test_auth_token_is_api_before_any_window(isolated_home):
    write_claude_json(isolated_home, ULTRA)
    env = env_for(isolated_home, ANTHROPIC_AUTH_TOKEN="x")
    assert account.load(env, make_session("startup")).mode == "api"


def test_plan_windows_on_stdin_mean_subscription(isolated_home):
    """A stray ANTHROPIC_AUTH_TOKEN doesn't matter once the CLI sends plan windows."""
    write_claude_json(isolated_home, ULTRA)
    env = env_for(isolated_home, ANTHROPIC_AUTH_TOKEN="x")
    assert account.load(env, make_session()).mode == "subscription"


def test_api_key_counts_only_once_approved(isolated_home):
    key = "sk-ant-api03-" + "a" * 40
    write_claude_json(isolated_home, ULTRA)
    env = env_for(isolated_home, ANTHROPIC_API_KEY=key)
    assert account.load(env, make_session("startup")).mode == "subscription"
    write_claude_json(isolated_home, ULTRA, customApiKeyResponses={"approved": [key[-20:]]})
    assert account.load(env, make_session("startup")).mode == "api"


def test_env_oauth_token_without_account_is_subscription(isolated_home):
    env = env_for(isolated_home, CLAUDE_CODE_OAUTH_TOKEN="t")
    acct = account.load(env, make_session("startup"))
    assert (acct.mode, acct.label, acct.fingerprint) == ("subscription", None, "env")


def test_config_dir_holds_claude_json(tmp_path):
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / ".claude.json").write_text(json.dumps({"oauthAccount": ULTRA}))
    acct = account.load({"CLAUDE_CONFIG_DIR": str(conf)}, make_session())
    assert acct.label == "Ultra"


def test_unreadable_claude_json_is_no_login(isolated_home):
    (isolated_home / ".claude.json").write_text("{not json")
    assert account.load(env_for(isolated_home), make_session("startup")).mode == "api"


# ---- label ----


@pytest.mark.parametrize(
    ("oauth", "label"),
    [
        (ULTRA, "Ultra"),
        (ENTERPRISE, "Enterprise"),
        ({"organizationType": "claude_team"}, "Team"),
        ({"organizationType": "claude_pro"}, "Pro"),
        ({"organizationType": "claude_max", "organizationRateLimitTier": "x_5x"}, "Max"),
        ({"organizationType": "claude_max", "organizationRateLimitTier": "x_20x"}, "Ultra"),
        ({"planDisplayName": "  Max  ", "organizationType": "claude_pro"}, "Max"),
        ({"planDisplayName": "", "organizationType": "claude_pro"}, "Pro"),
        ({"organizationType": "claude_mystery"}, None),
    ],
)
def test_plan_label(isolated_home, oauth, label):
    assert account.plan_label(oauth, env_for(isolated_home)) == label


@pytest.mark.parametrize(
    ("sub", "tier", "label"),
    [
        ("pro", None, "Pro"),
        ("max", "default_claude_max_5x", "Max"),
        ("max", "default_claude_max_20x", "Ultra"),
        ("team", None, "Team"),
        ("enterprise", None, "Enterprise"),
        ("weird", None, None),
    ],
)
def test_plan_label_from_credentials(isolated_home, sub, tier, label):
    write_credentials(isolated_home, subscriptionType=sub, rateLimitTier=tier)
    assert account.plan_label({}, env_for(isolated_home)) == label


def test_enterprise_is_team_spend(isolated_home):
    write_claude_json(isolated_home, ENTERPRISE)
    acct = account.load(env_for(isolated_home), make_session("startup"))
    assert acct.label == "Enterprise"
    assert acct.team


def test_fingerprint_is_a_hash_of_the_ids(isolated_home):
    write_claude_json(isolated_home, ULTRA)
    acct = account.load(env_for(isolated_home), make_session())
    ids = f"{ULTRA['accountUuid']}:{ULTRA['organizationUuid']}"
    assert acct.fingerprint == hashlib.sha256(ids.encode()).hexdigest()[:16]
    assert account.identity(env_for(isolated_home)) == acct.fingerprint
    assert ULTRA["accountUuid"] not in acct.fingerprint


# ---- trial ----


def trial_account(ends_at):
    return account.Account("subscription", "Pro", trial_ends_at=ends_at)


@pytest.mark.parametrize(
    ("left", "text"),
    [
        (5 * 86400, "trial 5d"),
        (4 * 86400 + 1, "trial 5d"),
        (86400, "trial 1d"),
        (86399, "trial 24h"),
        (3600 * 7 - 5, "trial 7h"),
        (30, "trial 1h"),
        (0, None),
        (-10, None),
    ],
)
def test_trial_text(left, text):
    assert account.trial_text(trial_account(NOW + left), NOW) == text


def test_trial_from_claude_json(isolated_home):
    oauth = dict(ULTRA, planDisplayName="Pro", claudeCodeTrialEndsAt="2026-11-10T00:00:00Z")
    write_claude_json(isolated_home, oauth)
    acct = account.load(env_for(isolated_home), make_session())
    g = glyphs.get("unicode")
    assert account.label_text(acct, g, NOW) == "Pro · trial 5d"
    assert account.label_text(acct, glyphs.get("ascii"), NOW) == "Pro / trial 5d"


def test_label_text_without_trial():
    g = glyphs.get("unicode")
    assert account.label_text(account.Account("api", "API"), g, NOW) == "API"
    assert account.label_text(account.Account("subscription"), g, NOW) is None


# ---- token ----


def test_keychain_names():
    assert account.keychain_service({}) == "Claude Code-credentials"
    digest = hashlib.sha256(b"/tmp/conf").hexdigest()[:8]
    assert account.keychain_service({"CLAUDE_CONFIG_DIR": "/tmp/conf"}) == (
        f"Claude Code-credentials-{digest}"
    )
    assert account.keychain_account({"USER": "mason"}) == "mason"
    assert account.keychain_account({"USER": "bad user"}) == "claude-code-user"
    assert account.keychain_account({}) == "claude-code-user"


def test_token_from_env_first(isolated_home):
    write_credentials(isolated_home, accessToken="file-token", expiresAt=(NOW + 3600) * 1000)
    env = env_for(isolated_home, CLAUDE_CODE_OAUTH_TOKEN="env-token")
    assert account.read_token(env, NOW, "linux") == ("env-token", None)


def test_token_from_file(isolated_home):
    write_credentials(isolated_home, accessToken="file-token", expiresAt=(NOW + 3600) * 1000)
    assert account.read_token(env_for(isolated_home), NOW, "linux") == ("file-token", None)


def test_expired_token(isolated_home):
    write_credentials(isolated_home, accessToken="old", expiresAt=(NOW + 30) * 1000)
    token, why = account.read_token(env_for(isolated_home), NOW, "linux")
    assert token is None
    assert why.startswith("token expired")


def test_no_token(isolated_home):
    assert account.read_token(env_for(isolated_home), NOW, "linux") == (
        None,
        "no Claude login found",
    )
    write_credentials(isolated_home, accessToken="")
    assert account.read_token(env_for(isolated_home), NOW, "linux")[0] is None


def test_keychain_before_file_on_macos(isolated_home, monkeypatch):
    write_credentials(isolated_home, accessToken="file-token")
    calls = []

    def keychain(env):
        calls.append(env)
        return {"claudeAiOauth": {"accessToken": "keychain-token"}}

    monkeypatch.setattr(account, "_read_keychain", keychain)
    assert account.read_token(env_for(isolated_home), NOW, "darwin") == ("keychain-token", None)
    assert account.read_token(env_for(isolated_home), NOW, "linux") == ("file-token", None)
    assert len(calls) == 1


def test_keychain_miss_falls_back_to_file(isolated_home, monkeypatch):
    write_credentials(isolated_home, accessToken="file-token")
    monkeypatch.setattr(account, "_read_keychain", lambda env: {})
    assert account.read_token(env_for(isolated_home), NOW, "darwin") == ("file-token", None)


def test_keychain_reader_runs_security(monkeypatch):
    import subprocess

    seen = {}

    class Done:
        returncode = 0
        stdout = json.dumps({"claudeAiOauth": {"accessToken": "k"}})

    def run(argv, **kwargs):
        seen["argv"] = argv
        return Done()

    monkeypatch.setattr(subprocess, "run", run)
    env = {"USER": "mason"}
    assert account._read_keychain(env) == {"claudeAiOauth": {"accessToken": "k"}}
    assert seen["argv"] == [
        "security",
        "find-generic-password",
        "-a",
        "mason",
        "-w",
        "-s",
        "Claude Code-credentials",
    ]
    Done.returncode = 44
    assert account._read_keychain(env) == {}
