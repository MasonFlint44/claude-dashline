"""The usage endpoint: cache, lock, hold, background fetch, and the plan bars (PLAN §1, §3, §4).

A render never waits on the network. It reads `usage.json`; when that is missing or older
than FRESH, it takes `fetch.lock` and starts a detached child that fetches once and
writes either a fresh `usage.json` or a `fetch.hold` saying when to try again and why.
Several Claude Code sessions share the cache, so the lock keeps them to one fetch.

Times written by another process (the cache's fetch time, the lock, the hold) can be
ahead of the clock if it has been set back (an NTP step, a manual change, a restored VM
snapshot; daylight saving doesn't move epoch time). Anything more than CLOCK_SLACK ahead
counts as unknown, so it can't freeze the cache, the lock or the hold.

The endpoint is undocumented: any shape it returns that we don't understand hides a bar,
never raises.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys

from dashline.stdin import _dig, _num, _str, iso_time
from dashline.text import clean
from dashline.theme import config_dir

API_URL = "https://api.anthropic.com"
USAGE_PATH = "/api/oauth/usage"
BETA = "oauth-2025-04-20"
TIMEOUT = 10
FRESH = 180  # refetch once the cache is this old
STALE = 300  # past this, line 2 shows the age (a fetch is failing)
MAX_AGE = 86400  # older data is dropped, not drawn
LOCK_STALE = 60  # a lock this old belongs to a child that died
CLOCK_SLACK = 60  # a time further ahead than this means the clock was set back
MAX_BODY = 1 << 20  # a usage answer is a few KB; anything past 1 MiB is not one
# Backoff after a failure: the first wait and the cap.
BACKOFF_FIRST, BACKOFF_MAX = 60, 1800
# The longest Retry-After honored: past it the value is nonsense, not a request.
RETRY_MAX = 86400
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


def hold(env, who: str | None, now: float | None = None) -> dict | None:
    """The current hold if it is for this login (by fingerprint). Callers compare `until`.

    With `now`, a hold written after `now` (the clock was set back), or one longer than
    any dashline writes, is ignored.
    """
    data = _read_json(_path(env, "fetch.hold"))
    until = _num(data.get("until"))
    if until is None or data.get("account") != who:
        return None
    if now is not None:
        at = _num(data.get("at"))
        if (at is not None and at > now + CLOCK_SLACK) or until > now + RETRY_MAX + CLOCK_SLACK:
            return None
    data["until"] = until
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
    elif fetched_at > now + CLOCK_SLACK:
        age = None  # fetched "later" than now: the clock was set back, so age is unknown
    else:
        age = max(0.0, now - fetched_at)
        if age > MAX_AGE:
            data, age = None, None
    held = hold(env, account.fingerprint, now)
    wait = held is not None and held["until"] > now
    due = data is None or age is None or age >= FRESH
    return State(data, age, fetch=due and not wait)


# ---- fetching ----


def _lock_id(path: str):
    """(identity, `at`, mtime) for the lock at `path`, or None if it's gone.

    The identity is the inode, mtime and content together: an inode number alone can be
    reused at once by the next lock. `at` is None until the content is written.
    """
    try:
        with open(path, "rb") as f:
            st = os.fstat(f.fileno())
            raw = f.read(4096)
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}  # still being written, or not ours
    at = _num(data.get("at")) if isinstance(data, dict) else None
    return (st.st_ino, st.st_mtime_ns, raw), at, st.st_mtime


def _lock_live(age: float) -> bool:
    """A lock this old is held by a running child; one from the future is not."""
    return -CLOCK_SLACK <= age < LOCK_STALE


def _break_lock(path: str, stale, now: float) -> None:
    """Remove the lock judged stale (`stale`, its identity), and only it.

    Breakers take `fetch.lock.break` first, so only one at a time can remove a lock;
    the others leave it to that one. A guard left by a breaker that died goes after
    LOCK_STALE.
    """
    guard = path + ".break"
    try:
        fd = os.open(guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with contextlib.suppress(OSError):
            if not _lock_live(now - os.stat(guard).st_mtime):
                _remove(guard)
        return
    except OSError:
        return
    os.close(fd)
    try:
        current = _lock_id(path)
        if current is not None and current[0] == stale:
            _remove(path)
    finally:
        _remove(guard)


def take_lock(env, now: float) -> str | None:
    """Create fetch.lock, or report that a live child holds it (None).

    Returns the lock's nonce: the child releases the lock only while it still holds this
    one, never a lock another process took after this one went stale.
    """
    path = _path(env, "fetch.lock")
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    nonce = os.urandom(8).hex()
    for _ in range(3):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            found = _lock_id(path)
            if found is None:
                continue  # it just went away: try again
            ident, at, mtime = found
            if _lock_live(now - (at if at is not None else mtime)):
                return None
            _break_lock(path, ident, now)  # its child died, or the clock was set back
            continue
        with os.fdopen(fd, "w") as f:
            json.dump({"at": now, "pid": os.getpid(), "nonce": nonce}, f)
        return nonce
    return None


def release(env, nonce: str | None) -> None:
    """Remove fetch.lock if it is still the one taken with `nonce`."""
    path = _path(env, "fetch.lock")
    if nonce and _read_json(path).get("nonce") == nonce:
        _remove(path)


def spawn(env, now: float) -> bool:
    """Start the detached fetch child. Returns False if one is already running."""
    nonce = take_lock(env, now)
    if not nonce:
        return False
    import subprocess

    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from dashline.usage import child; child(sys.argv[2])"
    )
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", code, package_parent, nonce],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=dict(env),
            cwd=package_parent,
            **kwargs,
        )
    except OSError:
        release(env, nonce)
        return False
    return True


def child(nonce: str | None = None) -> None:
    """The detached child's entry point: one refresh, then release its lock.

    A failure refresh didn't foresee still writes a backoff hold, so renders don't start
    a new fetch every time.
    """
    import time

    env = os.environ
    now = time.time()
    try:
        refresh(env, now)
    except Exception as e:
        # Nowhere to show a traceback; doctor runs refresh in the foreground.
        with contextlib.suppress(Exception):
            from dashline import account as account_mod

            _backoff(env, account_mod.identity(env), now, f"fetch failed ({type(e).__name__})")
    finally:
        release(env, nonce)


def retry_after(value, now: float) -> float | None:
    """A Retry-After header, seconds (`120`) or an HTTP date, as seconds from `now`."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(value)  # float: a 5000-digit value is inf, not an error
    from email.utils import parsedate_to_datetime

    try:
        when = parsedate_to_datetime(value)
        if when is None:
            return None
        if when.tzinfo is None:
            from datetime import timezone

            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, when.timestamp() - now)
    except Exception:  # 3.9 raises TypeError on garbage, later versions ValueError
        return None


def get(url: str, token: str, timeout: float = TIMEOUT, now: float | None = None) -> tuple:
    """GET the endpoint: (status, parsed JSON or None, Retry-After seconds or None).

    Status 0 means the request never got a whole HTTP answer (DNS, refused, timeout, a
    connection cut mid-answer). Redirects are refused, so the token only ever goes to
    `url`'s host: a 3xx comes back as its status.
    """
    import http.client
    import urllib.error
    import urllib.request

    from dashline import __version__

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None  # urllib then raises the 3xx as an HTTPError

    if now is None:
        import time

        now = time.time()
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": BETA,
            "Accept": "application/json",
            "User-Agent": f"dashline/{__version__}",
        },
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as r:
            status, body, headers = r.status, r.read(MAX_BODY + 1), r.headers
    except urllib.error.HTTPError as e:
        status, body, headers = e.code, b"", e.headers
    except (OSError, ValueError, http.client.HTTPException):
        return 0, None, None
    retry = retry_after(headers.get("Retry-After"), now) if headers is not None else None
    try:
        data = json.loads(body) if body and len(body) <= MAX_BODY else None
    except ValueError:
        data = None
    return status, data, retry


def _set_hold(env, who, now: float, seconds: float, reason: str, failures: int = 0):
    _write_json(
        _path(env, "fetch.hold"),
        {"until": now + seconds, "at": now, "reason": reason, "failures": failures, "account": who},
    )


def _backoff(env, who, now: float, reason: str, retry: float | None = None) -> None:
    """Hold after a failure: 60 s doubling to 30 min, or longer if the server asked."""
    previous = hold(env, who, now) or {}
    failures = int(min(max(_num(previous.get("failures")) or 0, 0), 30)) + 1
    wait = min(BACKOFF_MAX, BACKOFF_FIRST * 2 ** (failures - 1))
    if retry is not None:
        wait = max(wait, min(retry, RETRY_MAX))
    _set_hold(env, who, now, wait, reason, failures)


def refresh(env, now: float, base_url: str | None = None, platform: str | None = None) -> str:
    """Fetch once and write usage.json or fetch.hold. Returns what happened, in words."""
    from dashline import account as account_mod

    who = account_mod.identity(env)
    token, why = account_mod.read_token(env, now, platform)
    if token is None:
        expired = why.startswith("token expired")
        _set_hold(env, who, now, HOLDS["expired" if expired else "no-token"], why)
        return why
    status, data, retry = get((base_url or API_URL).rstrip("/") + USAGE_PATH, token, now=now)
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
    if status == 200:
        reason = "unreadable answer"
    elif 300 <= status < 400:
        reason = f"redirect refused (HTTP {status})"
    elif status:
        reason = f"HTTP {status}"
    else:
        reason = "no answer (network)"
    _backoff(env, who, now, reason, retry if status else None)
    return reason


# ---- bars ----


def _money(value) -> float | None:
    """`{"amount_minor": 1234, "exponent": 2}` → 12.34."""
    minor, exponent = _num(_dig(value, "amount_minor")), _num(_dig(value, "exponent"))
    if minor is None or not 0 <= (exponent or 0) <= 18:
        return None
    return minor / 10 ** int(exponent or 0)


def _model_matches(scope_name: str, session) -> bool:
    """`Fable` scopes `Fable 5.1` / `claude-fable-5-1`."""
    name = scope_name.strip().lower()
    if not name:
        return False
    shown = (session.model or "").lower()
    return shown == name or shown.startswith(name + " ") or name in (session.model_id or "")


def _live(window, now: float) -> tuple | None:
    """A stdin window as (percent, resets_at); one whose reset has passed reads 0%.

    Claude Code sends the window it saw on the last response, so while you're idle it
    can be one that has since rolled over.
    """
    if window is None:
        return None
    if window.resets_at is not None and window.resets_at <= now:
        return 0.0, None
    return window.percent, window.resets_at


def _merge(endpoint: tuple, other: tuple | None) -> tuple:
    """One window from both sources: the later window wins, else the higher percent.

    stdin comes with every API response, so it is often fresher than the cache.
    """
    if other is None:
        return endpoint
    percent, resets_at = endpoint
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
            percent, resets_at = _merge((percent, resets_at), _live(session.windows.get(key), now))
            windows.append(Bar(WINDOW_LABELS[kind], percent, resets_at))
        elif kind == "weekly_scoped":
            # A model's weekly limit: shown while you use that model (even at 0%), and
            # whenever it has use this week, since subagents and other sessions spend it.
            name = _str(_dig(row, "scope", "model", "display_name"))
            if name and (percent > 0 or _model_matches(name, session)):
                windows.append(Bar(clean(name), percent, resets_at))
        else:
            windows.append(Bar(clean(kind.replace("_", " ")), percent, resets_at))

    # Windows the endpoint didn't list (or no cache yet) still come from stdin.
    stdin_only = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        window = _live(session.windows.get(key), now)
        if window and key not in used_stdin:
            stdin_only.append(Bar(label, *window))
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
        caps.append(Bar(period, *_live(gateway, now)))
    return windows + caps + credits
