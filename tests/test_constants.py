"""The numbers PLAN, README and CHANGELOG promise. Other tests take most of these from
the constants themselves, so a change there would pass them all: here each is written
out, and changing one means changing the docs too."""

import ast
import inspect

from dashline import account, doctor, layout, repo, text, theme, usage

MIB = 1 << 20


def test_fetching():
    assert usage.FRESH == 180  # PLAN §3: a cache ≥ 3 min old is refetched
    assert usage.LOCK_STALE == 60  # a lock ≥ 60 s old is broken
    assert (usage.TIMEOUT, usage.DEADLINE) == (10, 30)  # 10 s per step, 30 s in all
    assert usage.MAX_AGE == 86400  # data older than a day is dropped
    assert usage.MAX_LIMITS == 32  # limits kept and read
    assert usage.MAX_BODY == MIB  # a usage answer past 1 MiB isn't one


def test_reading_files():
    assert theme.MAX_JSON == 64 * MIB  # PLAN §3: settings and Claude's own files
    assert repo.MAX_GIT_FILE == MIB  # git's own files
    assert repo.GIT_TIMEOUT == 1.0  # PLAN §5: git gets 1 s in total


def test_showing():
    assert usage.MAX_LABEL == account.MAX_PLAN == 20  # bar labels and the plan name
    assert layout.MODEL_MIN == 16  # PLAN §4: the model name is cut down to 16
    assert text.MAX_SHOWN == 4096  # PLAN §7


def written(module, name):
    """A constant as the module's source sets it (conftest changes some for the tests)."""
    for node in ast.parse(inspect.getsource(module)).body:
        targets = [getattr(t, "id", None) for t in getattr(node, "targets", ())]
        if isinstance(node, ast.Assign) and targets == [name]:
            return ast.literal_eval(node.value)
    raise LookupError(name)


def test_doctor():
    # PLAN §2: slow past 500 ms, or 2.5 s on Windows (starting the shell takes most of it)
    assert (written(doctor, "SLOW_MS"), written(doctor, "SLOW_MS_WINDOWS")) == (500, 2500)
    assert doctor.LOCK_WAIT == 5  # PLAN §9: waits up to 5 s for a background fetch
