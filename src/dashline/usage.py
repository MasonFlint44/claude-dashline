"""The usage endpoint: cache, lock, hold, background fetch, and the plan bars (PLAN §1, §3, §4).

A render never waits on the network. It reads `usage.json`; when that is missing or older
than FRESH, it takes `fetch.lock` and starts a detached child that fetches once and
writes either a fresh `usage.json` or a `fetch.hold` saying when to try again and why.
Several Claude Code sessions share the cache, so the lock keeps them to one fetch.

The endpoint is undocumented: any shape it returns that we don't understand hides a bar,
never raises.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys

from dashline.stdin import _dig, _num, _str, iso_time
from dashline.theme import config_dir

API_URL = "https://api.anthropic.com"
USAGE_PATH = "/api/oauth/usage"
BETA = "oauth-2025-04-20"
TIMEOUT = 10
FRESH = 180  # refetch once the cache is this old
STALE = 300  # past this, line 2 shows the age (a fetch is failing)
MAX_AGE = 86400  # older data is dropped, not drawn
LOCK_STALE = 60  # a lock this old belongs to a child that died
# Backoff after a failure: the first wait and the cap.
BACKOFF_FIRST, BACKOFF_MAX = 60, 1800
# Fixed waits for answers a retry won't change soon.
HOLDS = {
    "no-token": 600,
    "expired": 300,
    401: 300,
    403: 3600,
    404: 6 * 3600,
}
WINDOW_LABELS = {"session": "5h", "weekly_all": "7d"}
STDIN_WINDOWS = {"session": "five_hour", "weekly_all": "seven_day"}
PERIODS = {"month": "month", "monthly": "month", "week": "week", "weekly": "week"}


def cache_dir(env) -> str:
    return os.path.join(config_dir(env), "cache", "statusline")


def _path(env, name: str) -> str:
    return os.path.join(cache_dir(env), name)


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: str, data: dict) -> None:
    """Write atomically: readers see the old file or the new one, never half of one."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _remove(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)


# ---- what a render reads ----


class State:
    """The cached usage for this account: data (or None), its age, and whether to fetch."""

    def __init__(self, data: dict | None = None, age: float | None = None, fetch=False):
        self.data = data
        self.age = age
        self.fetch = fetch

    @property
    def stale_age(self) -> float | None:
        """The age to show on line 2, once the data is old enough to say so."""
        if self.data is not None and self.age is not None and self.age >= STALE:
            return self.age
        return None


def hold(env, who: str | None) -> dict | None:
    """The current hold if it is for this login (by fingerprint). Callers compare `until`."""
    data = _read_json(_path(env, "fetch.hold"))
    if _num(data.get("until")) is None or data.get("account") != who:
        return None
    return data


def load(env, account, now: float) -> State:
    if account.mode != "subscription":
        return State()
    cache = _read_json(_path(env, "usage.json"))
    data, age = cache.get("data"), None
    fetched_at = _num(cache.get("fetched_at"))
    if not isinstance(data, dict) or fetched_at is None:
        data = None
    elif cache.get("account") != account.fingerprint:
        data = None  # someone else's usage: a different login
    else:
        age = max(0.0, now - fetched_at)
        if age > MAX_AGE:
            data, age = None, None
    held = hold(env, account.fingerprint)
    wait = held is not None and held["until"] > now
    return State(data, age, fetch=(data is None or age >= FRESH) and not wait)


# ---- fetching ----


def take_lock(env, now: float) -> bool:
    """Create fetch.lock, or report that a live child holds it."""
    path = _path(env, "fetch.lock")
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            at = _num(_read_json(path).get("at"))
            if at is None:
                try:
                    at = os.stat(path).st_mtime
                except OSError:
                    continue  # it just went away: try again
            if now - at < LOCK_STALE:
                return False
            _remove(path)
            continue
        with os.fdopen(fd, "w") as f:
            json.dump({"at": now, "pid": os.getpid()}, f)
        return True
    return False


def spawn(env, now: float) -> bool:
    """Start the detached fetch child. Returns False if one is already running."""
    if not take_lock(env, now):
        return False
    import subprocess

    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = "import sys; sys.path.insert(0, sys.argv[1]); from dashline.usage import child; child()"
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", code, package_parent],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=dict(env),
            cwd=package_parent,
            **kwargs,
        )
    except OSError:
        _remove(_path(env, "fetch.lock"))
        return False
    return True


def child() -> None:
    """The detached child's entry point: one refresh, then release the lock."""
    import time

    env = os.environ
    try:
        refresh(env, time.time())
    except Exception:
        pass  # nowhere to report it; doctor runs refresh in the foreground
    finally:
        _remove(_path(env, "fetch.lock"))


def get(url: str, token: str, timeout: float = TIMEOUT) -> tuple:
    """GET the endpoint: (status, parsed JSON or None, Retry-After seconds or None).

    Status 0 means the request never got an HTTP answer (DNS, refused, timeout).
    """
    import urllib.error
    import urllib.request

    from dashline import __version__

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": BETA,
            "Accept": "application/json",
            "User-Agent": f"dashline/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            status, body, headers = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, body, headers = e.code, b"", e.headers
    except (OSError, ValueError):
        return 0, None, None
    retry = headers.get("Retry-After") if headers is not None else None
    retry = int(retry) if retry and retry.strip().isdigit() else None
    try:
        data = json.loads(body) if body else None
    except ValueError:
        data = None
    return status, data, retry


def _set_hold(env, who, now: float, seconds: float, reason: str, failures: int = 0):
    _write_json(
        _path(env, "fetch.hold"),
        {"until": now + seconds, "reason": reason, "failures": failures, "account": who},
    )


def refresh(env, now: float, base_url: str = API_URL, platform: str | None = None) -> str:
    """Fetch once and write usage.json or fetch.hold. Returns what happened, in words."""
    from dashline import account as account_mod

    who = account_mod.identity(env)
    token, why = account_mod.read_token(env, now, platform)
    if token is None:
        expired = why.startswith("token expired")
        _set_hold(env, who, now, HOLDS["expired" if expired else "no-token"], why)
        return why
    status, data, retry = get(base_url.rstrip("/") + USAGE_PATH, token)
    del token
    if status == 200 and isinstance(data, dict):
        _write_json(
            _path(env, "usage.json"),
            {"fetched_at": now, "account": who, "data": data},
        )
        _remove(_path(env, "fetch.hold"))
        return "ok"
    if status in HOLDS:
        reason = {
            401: "token rejected (401)",
            403: "not allowed (403): the login may lack the profile scope",
            404: "usage endpoint not found (404)",
        }[status]
        _set_hold(env, who, now, HOLDS[status], reason)
        return reason
    previous = hold(env, who) or {}
    failures = int(_num(previous.get("failures")) or 0) + 1
    wait = min(BACKOFF_MAX, BACKOFF_FIRST * 2 ** (failures - 1))
    if status == 429 and retry:
        wait = max(wait, min(retry, BACKOFF_MAX))
    if status == 200:
        reason = "unreadable answer"
    elif status:
        reason = f"HTTP {status}"
    else:
        reason = "no answer (network)"
    _set_hold(env, who, now, wait, reason, failures)
    return reason


# ---- bars ----


def _money(value) -> float | None:
    """`{"amount_minor": 1234, "exponent": 2}` → 12.34."""
    minor, exponent = _num(_dig(value, "amount_minor")), _num(_dig(value, "exponent"))
    if minor is None:
        return None
    return minor / 10 ** int(exponent or 0)


def _model_matches(scope_name: str, session) -> bool:
    """`Fable` scopes `Fable 5.1` / `claude-fable-5-1`."""
    name = scope_name.strip().lower()
    if not name:
        return False
    shown = (session.model or "").lower()
    return shown == name or shown.startswith(name + " ") or name in (session.model_id or "")


def _merge(endpoint: tuple, stdin_window) -> tuple:
    """One window from both sources: the later window wins, else the higher percent.

    stdin comes with every API response, so it is often fresher than the cache.
    """
    if stdin_window is None:
        return endpoint
    percent, resets_at = endpoint
    other = (stdin_window.percent, stdin_window.resets_at)
    if resets_at and other[1] and abs(resets_at - other[1]) > 60:
        return endpoint if resets_at > other[1] else other
    return (max(percent, other[0]), resets_at or other[1])


def plan_bars(session, account, data: dict | None, now: float) -> list:
    """Line 2's bars from the usage response and stdin, in display order."""
    from dashline.layout import Bar

    data = data if isinstance(data, dict) else {}
    spend = data.get("spend") if isinstance(data.get("spend"), dict) else {}
    windows, used_stdin = [], set()

    limits = data.get("limits")
    for row in limits if isinstance(limits, list) else []:
        if not isinstance(row, dict):
            continue
        kind, percent = _str(row.get("kind")), _num(row.get("percent"))
        if kind is None or percent is None:
            continue
        resets_at = iso_time(row.get("resets_at"))
        if resets_at is not None and resets_at <= now:
            percent, resets_at = 0.0, None  # the window rolled over since the fetch
        if kind in WINDOW_LABELS:
            key = STDIN_WINDOWS[kind]
            used_stdin.add(key)
            percent, resets_at = _merge((percent, resets_at), session.windows.get(key))
            windows.append(Bar(WINDOW_LABELS[kind], percent, resets_at))
        elif kind == "weekly_scoped":
            # A model's weekly limit: shown while you use that model (even at 0%), and
            # whenever it has use this week, since subagents and other sessions spend it.
            name = _str(_dig(row, "scope", "model", "display_name"))
            if name and (percent > 0 or _model_matches(name, session)):
                windows.append(Bar(name, percent, resets_at))
        else:
            windows.append(Bar(kind.replace("_", " "), percent, resets_at))

    # Windows the endpoint didn't list (or no cache yet) still come from stdin.
    stdin_only = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        window = session.windows.get(key)
        if window and key not in used_stdin:
            stdin_only.append(Bar(label, window.percent, window.resets_at))
    windows = stdin_only + windows
    windows.sort(key=lambda b: {"5h": 0, "7d": 1}.get(b.label, 2))

    # Spend: Team / Enterprise caps are a monthly bar; elsewhere it is extra-usage credits.
    caps, credits = [], []
    enabled = spend.get("enabled") is True
    used, limit = _money(spend.get("used")), _money(spend.get("limit"))
    percent = _num(spend.get("percent"))
    if percent is None and used is not None and limit:
        percent = used / limit * 100
    if enabled and percent is not None and limit:
        if account.team:
            caps.append(Bar("month", percent))
        elif used:
            credits.append(Bar("credits", percent))
    if session.spend_limit is not None:
        gateway = session.spend_limit
        period = PERIODS.get((gateway.period or "").lower(), "month")
        caps.append(Bar(period, gateway.percent, gateway.resets_at))
    return windows + caps + credits
