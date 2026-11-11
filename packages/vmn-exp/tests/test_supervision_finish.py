"""The end of `vmn-exp run`: a final state or final log sync that did not
reach the remote is warned about, within one budget (plan 40 C15). Driven
without a child process: a stub with a return code stands in for it."""
import argparse
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from supervisor_fakes import APP, V, FakeRemote, FakeWait, local_first

from vmn_exp.cli import run as runmod
from vmn_exp.cli import supervisor
from vmn_exp.cli.run import _Supervision
from vmn_exp.cli.supervisor_state import finish_uploads, not_uploaded_warning
from vmn_exp.storage.buffered import BufferedRemoteStorage


@pytest.fixture
def logger(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supervisor, "VMN_LOGGER", fake)
    monkeypatch.setattr(runmod, "VMN_LOGGER", fake)
    return fake


def _warnings(logger):
    return [c.args[0] for c in logger.warning.call_args_list]


class _NoMetrics:
    def poll(self):
        return []


def _finish(storage, wait):
    args = argparse.Namespace(capture_output=False, kill_grace_sec=1)
    sup = _Supervision(storage, APP, V, args, wait=wait)
    sup.start, sup.tailer = 0.0, _NoMetrics()
    sup.run_state = {"state": "running", "attempt": "a1", "exit_code": None}
    return sup._finish(SimpleNamespace(returncode=0), ["train"])


def test_finish_warns_that_the_final_state_was_not_uploaded_and_names_push(tmp_path, logger):
    remote = FakeRemote(str(tmp_path / "remote"), failures=100)

    assert _finish(local_first(tmp_path, remote), FakeWait(abandon_at=1)) == 0

    assert (f"Experiment {V}: the final run state was not uploaded: bucket down; "
            "run `vmn-exp push` to upload it") in _warnings(logger)


def test_finish_warns_that_the_final_log_sync_was_not_uploaded(tmp_path, logger):
    remote = FakeRemote(str(tmp_path / "remote"))
    storage = local_first(tmp_path, remote)
    remote.logs_down = True

    _finish(storage, FakeWait(abandon_at=1))

    assert _warnings(logger) == [
        "Experiment run: the final log sync was not uploaded: bucket down"
    ]


def test_a_clean_finish_warns_nothing(tmp_path, logger):
    remote = FakeRemote(str(tmp_path / "remote"))

    _finish(local_first(tmp_path, remote), FakeWait())

    assert _warnings(logger) == []
    assert b"state: finished" in remote.state_saves[-1].encode()


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class _SlowSync:
    """A final log sync that takes 40 of the clock's seconds."""

    def __init__(self, clock):
        self.clock = clock
        self.given = None

    def final(self, timeout):
        self.given = timeout
        self.clock.now += 40


class _StateUploads:
    def __init__(self):
        self.given = None

    def close(self, timeout):
        self.given = timeout
        return True


def test_the_final_sync_and_the_final_state_share_one_budget():
    clock = _Clock()
    sync, state = _SlowSync(clock), _StateUploads()

    assert finish_uploads(sync, state, deadline=160.0, clock=clock) is True

    assert (sync.given, state.given) == (60.0, 20.0)


class _SlowMetrics:
    """The child's last metrics, whose ingestion takes 50 of the clock's seconds."""

    def __init__(self, clock):
        self.clock = clock

    def poll(self):
        self.clock.now += 50
        return []


class _FinalSync(_StateUploads):
    def final(self, timeout):
        self.given = timeout


class _Published(_StateUploads):
    def publish(self, run_state, final=False):
        pass


def test_the_final_upload_budget_starts_when_the_final_state_is_submitted(tmp_path, monkeypatch, logger):
    clock = _Clock()
    monkeypatch.setattr(runmod, "time", SimpleNamespace(monotonic=clock))
    args = argparse.Namespace(capture_output=False, kill_grace_sec=1)
    sup = _Supervision(local_first(tmp_path, FakeRemote(str(tmp_path / "remote"))),
                       APP, V, args, wait=FakeWait())
    sup.start, sup.tailer = clock.now, _SlowMetrics(clock)
    sup.sync, sup.state_uploads = _FinalSync(), _Published()
    sup.run_state = {"state": "running", "attempt": "a1", "exit_code": None}

    sup._finish(SimpleNamespace(returncode=0), ["train"])

    assert sup.sync.given == runmod._FINAL_SYNC_TIMEOUT_SEC


def test_a_log_buffer_gets_no_push_hint(tmp_path):
    buffer = BufferedRemoteStorage(FakeRemote(str(tmp_path / "remote")), str(tmp_path / "buffers"))

    assert not_uploaded_warning(V, OSError("bucket down"), buffer) == (
        f"Experiment {V}: the final run state was not uploaded: bucket down")
