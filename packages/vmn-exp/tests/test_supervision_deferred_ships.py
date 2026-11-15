"""`vmn-exp run` direct to a bucket: a due ship of the log buffer is a request
to the supervisor's sync worker, never an upload on the supervise loop
(plan 40 C15, reusing C3's hand-off)."""
import argparse
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from deferred_ship_fakes import FakeBucket
from s3_helpers import entry, meta
from supervisor_fakes import APP, V, FakeWait

from vmn_exp.cli import run as runmod
from vmn_exp.cli import supervisor
from vmn_exp.cli.run import _Supervision
from vmn_exp.core.real_io import real_io
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.core.real_io import RealClock


@pytest.fixture(autouse=True)
def _temp(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "buffers"))
    (tmp_path / "buffers").mkdir()
    yield
    buffered.close_all()


@pytest.fixture(autouse=True)
def _logger(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supervisor, "VMN_LOGGER", fake)
    monkeypatch.setattr(runmod, "VMN_LOGGER", fake)


@pytest.fixture
def bucket(tmp_path):
    remote = FakeBucket(str(tmp_path / "bucket"))
    remote.save(APP, V, meta(V), {})
    return remote


class _Sync:
    """The supervisor's sync worker; its final sync appends one more line."""

    def __init__(self, pod, bucket):
        self.requests = 0
        self.final_shipped_inline = None
        self._pod, self._bucket = pod, bucket

    def request(self):
        self.requests += 1

    def final(self, timeout):
        before = self._bucket.creates
        self._pod.append_log_entry(APP, V, "w", entry(0))
        self.final_shipped_inline = self._bucket.creates > before
        return True


def _supervision(bucket):
    pod = BufferedRemoteStorage(bucket, bucket.root + "-buffers", area="runs", clock=RealClock())
    args = argparse.Namespace(capture_output=False, kill_grace_sec=1)
    sup = _Supervision(pod, APP, V, args, wait=FakeWait(), io=real_io())
    sup.sync = _Sync(pod, bucket)
    sup._defer_ships()
    return sup


def test_ingesting_metrics_does_not_ship_on_the_supervise_loop(bucket):
    sup = _supervision(bucket)

    sup._ingest([(None, {"loss": 0.5})])

    assert bucket.creates == 0


def test_a_due_ship_becomes_a_sync_request(bucket):
    sup = _supervision(bucket)

    sup._ingest([(None, {"loss": 0.5})])

    assert sup.sync.requests == 1


def test_ships_are_undeferred_before_the_final_sync(bucket):
    sup = _supervision(bucket)
    sup.start, sup.tailer = 0.0, SimpleNamespace(poll=lambda: [])
    sup.run_state = {"state": "running", "attempt": "a1", "exit_code": None}

    sup._finish(SimpleNamespace(returncode=0), ["train"])

    assert sup.sync.final_shipped_inline is True
