"""The unit lane's guard: a test in packages/vmn-exp/tests/unit runs on fakes,
so a real sleep, a real child process or the Docker ``app_layout`` fixture
fails it. This is the only place allowed to patch ``time.sleep`` and
``subprocess.Popen``."""
import contextlib
import subprocess
import threading
import time

import pytest

DOCKER_FIXTURES = ("app_layout",)
# Taken before any guard patches them, so a nested guard still reaches the real call.
_REAL = {(time, "sleep"): time.sleep, (subprocess, "Popen"): subprocess.Popen}


def refuse_docker_fixtures(fixturenames):
    asked = [name for name in DOCKER_FIXTURES if name in fixturenames]
    if asked:
        pytest.fail(f"a unit test may not use {', '.join(asked)} (Docker); "
                    "move it out of tests/unit or use the fakes in tests/fakes")


@contextlib.contextmanager
def no_real_io():
    """Inside it, ``time.sleep`` and ``subprocess.Popen`` fail the calling
    thread and are recorded in the yielded list. Threads that were already
    running (pytest's and xdist's own) keep the real calls."""
    violations = []
    elders = {thread.ident for thread in threading.enumerate()} - {threading.get_ident()}
    with pytest.MonkeyPatch.context() as patch:
        for owner, name in _REAL:
            patch.setattr(owner, name, _forbidden(owner, name, elders, violations))
        yield violations


def _forbidden(owner, name, elders, violations):
    real = _REAL[owner, name]
    label = f"{owner.__name__}.{name}"

    def call(*args, **kwargs):
        if threading.get_ident() in elders:
            return real(*args, **kwargs)
        violations.append(label)
        pytest.fail(f"a unit test reached real {label}; inject a fake from tests/fakes")

    return call
