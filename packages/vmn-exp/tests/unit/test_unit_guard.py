"""The unit lane's guard (unit_guard.py, wired autouse in this directory's
conftest): a unit test that really sleeps, spawns a process or asks for the
Docker ``app_layout`` fixture fails."""
import subprocess
import sys
import threading
import time

import pytest

from unit_guard import no_real_io, refuse_docker_fixtures


def test_real_sleep_fails_a_unit_test():
    with no_real_io():
        with pytest.raises(pytest.fail.Exception, match="time.sleep"):
            time.sleep(0)


def test_real_popen_fails_a_unit_test():
    with no_real_io():
        with pytest.raises(pytest.fail.Exception, match="subprocess.Popen"):
            subprocess.run([sys.executable, "-c", "pass"])


def test_requesting_app_layout_fails_a_unit_test():
    with pytest.raises(pytest.fail.Exception, match="app_layout"):
        refuse_docker_fixtures(["tmp_path", "app_layout"])


def test_a_test_without_docker_fixtures_passes_the_guard():
    refuse_docker_fixtures(["tmp_path", "monkeypatch"])


def test_a_violation_in_a_thread_the_test_started_is_recorded():
    # A raise inside a thread does not fail the test by itself; the guard
    # keeps the violation so its fixture can fail the test afterwards.
    with no_real_io() as violations:
        worker = threading.Thread(target=lambda: _swallow(time.sleep, 0))
        worker.start()
        worker.join()
    assert violations == ["time.sleep"]


def test_threads_that_predate_the_guard_keep_the_real_calls():
    # pytest-xdist's own threads live before the test starts; the guard
    # leaves them alone.
    go = threading.Event()
    slept = []

    def sleeper():
        go.wait()
        time.sleep(0)
        slept.append(True)

    worker = threading.Thread(target=sleeper)
    worker.start()
    with no_real_io() as violations:
        go.set()
        worker.join()
    assert slept == [True] and violations == []


def _swallow(call, *args):
    try:
        call(*args)
    except BaseException:
        pass
