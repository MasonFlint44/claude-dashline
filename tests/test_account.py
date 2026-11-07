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
    assert (acct.mode, acct.label) == ("subscription", None)
    assert acct.fingerprint.startswith("env-")


def test_env_token_tags_the_cache_by_itself(isolated_home):
    """The env token wins over the stored login and may be another account's."""
    write_claude_json(isolated_home, ULTRA)
    stored = account.load(env_for(isolated_home), make_session()).fingerprint
    one = account.load(env_for(isolated_home, CLAUDE_CODE_OAUTH_TOKEN="tok-one"), make_session())
    two = account.load(env_for(isolated_home, CLAUDE_CODE_OAUTH_TOKEN="tok-two"), make_session())
    assert len({stored, one.fingerprint, two.fingerprint}) == 3
    assert "tok-one" not in one.fingerprint
    assert account.identity(env_for(isolated_home, CLAUDE_CODE_OAUTH_TOKEN="tok-one")) == (
        one.fingerprint
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"oauthAccount": {"organizationType": ["claude_max"], "accountUuid": {}}},
        {"oauthAccount": {"planDisplayName": ["Ultra"], "organizationType": {"a": 1}}},
        {"oauthAccount": [], "customApiKeyResponses": ["x"]},
        {"oauthAccount": {"accountUuid": "a", "organizationUuid": "o"}, "customApiKeyResponses": 3},
        {"customApiKeyResponses": {"approved": {"x": 1}}},
    ],
)
def test_odd_types_in_claude_json_read_as_missing(isolated_home, extra):
    (isolated_home / ".claude.json").write_text(json.dumps(extra))
    write_credentials(isolated_home, subscriptionType=["max"], rateLimitTier={"x": 1})
    env = env_for(isolated_home, ANTHROPIC_API_KEY="sk-ant-api03-" + "a" * 40)
    for session in (make_session(), make_session("startup")):
        acct = account.load(env, session)  # no TypeError / AttributeError
        assert acct.label in (None, "API")  # no plan to name; API when nothing says otherwise
        assert acct.org_type is None


def test_plan_name_control_characters_are_replaced(isolated_home):
    write_claude_json(isolated_home, dict(ULTRA, planDisplayName="Ul\x1b[31mtra\nX"))
    assert account.load(env_for(isolated_home), make_session()).label == "Ul?[31mtra?X"


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
    assert account.keychain_account({"USER": "user"}) == "user"
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

    def keychain(env, wait):
        calls.append(wait)
        return {"claudeAiOauth": {"accessToken": "keychain-token"}}

    monkeypatch.setattr(account, "_read_keychain", keychain)
    assert account.read_token(env_for(isolated_home), NOW, "darwin") == ("keychain-token", None)
    assert account.read_token(env_for(isolated_home), NOW, "linux") == ("file-token", None)
    assert calls == [account.KEYCHAIN_WAIT]


def test_keychain_miss_falls_back_to_file(isolated_home, monkeypatch):
    write_credentials(isolated_home, accessToken="file-token")
    monkeypatch.setattr(account, "_read_keychain", lambda env, wait: {})
    assert account.read_token(env_for(isolated_home), NOW, "darwin") == ("file-token", None)


@pytest.mark.real_keychain
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
    env = {"USER": "user"}
    assert account._read_keychain(env) == {"claudeAiOauth": {"accessToken": "k"}}
    assert seen["argv"] == [
        "security",
        "find-generic-password",
        "-a",
        "user",
        "-w",
        "-s",
        "Claude Code-credentials",
    ]
    Done.returncode = 44
    assert account._read_keychain(env) == {}


def fake_security(monkeypatch, returncode=0, stdout="", error=None):
    import subprocess

    class Done:
        pass

    def run(argv, **kwargs):
        if error is not None:
            raise error
        done = Done()
        done.returncode, done.stdout = returncode, stdout
        return done

    monkeypatch.setattr(subprocess, "run", run)


@pytest.mark.real_keychain
@pytest.mark.parametrize("stdout", ["not json", "[1]", "[" * 100000, ""])
def test_keychain_reader_odd_output_is_no_login(monkeypatch, stdout):
    fake_security(monkeypatch, stdout=stdout)
    assert account._read_keychain({}) == {}


@pytest.mark.real_keychain
def test_keychain_reader_without_security_is_no_login(monkeypatch):
    fake_security(monkeypatch, error=FileNotFoundError("security"))
    assert account._read_keychain({}) == {}


@pytest.mark.real_keychain
@pytest.mark.parametrize("returncode", [36, 51, 1])
def test_keychain_reader_locked_is_not_no_login(monkeypatch, returncode):
    """Over SSH a locked Keychain says "User interaction is not allowed": /login won't
    fix that, so it mustn't read as no login."""
    fake_security(monkeypatch, returncode=returncode)
    with pytest.raises(account.KeychainError):
        account._read_keychain({})


@pytest.mark.real_keychain
def test_keychain_reader_unanswered_prompt_is_locked(monkeypatch):
    import subprocess

    fake_security(monkeypatch, error=subprocess.TimeoutExpired("security", 5))
    with pytest.raises(account.KeychainError):
        account._read_keychain({})


def test_locked_keychain_says_so(isolated_home, monkeypatch):
    def locked(env, wait):
        raise account.KeychainError(account.KEYCHAIN_LOCKED)

    monkeypatch.setattr(account, "_read_keychain", locked)
    token, why, _ = account.find_token(env_for(isolated_home), NOW, "darwin")
    assert (token, why) == (None, account.KEYCHAIN_LOCKED)


def test_locked_keychain_still_falls_back_to_file(isolated_home, monkeypatch):
    def locked(env, wait):
        raise account.KeychainError(account.KEYCHAIN_LOCKED)

    write_credentials(isolated_home, accessToken="file-token")
    monkeypatch.setattr(account, "_read_keychain", locked)
    assert account.read_token(env_for(isolated_home), NOW, "darwin") == ("file-token", None)


# ---- 0.1.7 review ----


def test_claude_json_comes_from_the_envs_home(tmp_path, isolated_home):
    """The caller's env decides where ~ is, never the process's HOME."""
    import os

    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / ".claude.json").write_text(
        json.dumps(
            {
                "oauthAccount": {
                    "planDisplayName": "Pro",
                    "accountUuid": "a",
                    "organizationUuid": "o",
                }
            }
        )
    )
    env = {"HOME": str(other)}
    assert os.environ["HOME"] != str(other)
    assert account.claude_json_path(env) == str(other / ".claude.json")
    assert account.load(env).label == "Pro"
    assert account.identity(env) is not None
    assert account.identity({"HOME": str(isolated_home)}) is None  # nothing there


def test_deeply_nested_claude_json_reads_as_empty(isolated_home):
    (isolated_home / ".claude.json").write_text('{"a": ' * 100000 + "1" + "}" * 100000)
    acct = account.load({"HOME": str(isolated_home)})
    assert acct.mode == "api"


def test_trial_countdown_is_capped():
    acct = account.Account("subscription", "Pro", trial_ends_at=NOW + 1e12)
    assert account.trial_text(acct, NOW) == "trial 999d"
    acct = account.Account("subscription", "Pro", trial_ends_at=NOW + 998 * 86400)
    assert account.trial_text(acct, NOW) == "trial 998d"


def test_team_is_team_spend():
    assert account.Account("subscription", "Team", org_type="claude_team").team


def test_a_team_named_without_its_type_is_team_spend():
    """An older .claude.json may have the plan's name and no organization type."""
    assert account.Account("subscription", "Team").team
    assert account.Account("subscription", "Enterprise").team
    assert not account.Account("subscription", "Max").team
