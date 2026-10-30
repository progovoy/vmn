"""A losing attempt's heartbeat never overwrites the winner's final state.

Two attempts of one run share its ``run_state.yml``. A finish is a
compare-and-swap; so is every other state write — each heartbeat, and the
first write of a resumed attempt — so a beat that read the state before
another attempt finished the run cannot then flip it back to running and
erase its exit code. A beat on the token of its own last write still costs
one conditional PUT and no read.
"""
import time

import pytest
import yaml
from s3_helpers import meta, mocked_bucket, s3_storage

from vmn_exp.core.status import load_run_state
from vmn_exp.sdk.run import Run
from vmn_exp.sdk.state_publisher import RunStatePublisher
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
X = "0.0.1-dev.abc1234.0000001"


def _running(seq, attempt):
    return {"state": "running", "attempt": attempt, "heartbeat_seq": seq, "exit_code": None}


def _final(attempt):
    return {"state": "finished", "attempt": attempt, "exit_code": 0}


def _local(root):
    return LocalSnapshotStorage(str(root), "runs")


@pytest.fixture
def root(tmp_path):
    _local(tmp_path).save(APP, X, meta(X), {})
    return tmp_path


def _before_next(storage, methods, action):
    """Run *action* once, right before *storage*'s next call of one of *methods*."""
    for name in methods:
        real = getattr(storage, name)

        def hooked(*args, _real=real, **kwargs):
            if not storage.__dict__.get("_fired"):
                storage._fired = True
                action()
            return _real(*args, **kwargs)

        setattr(storage, name, hooked)


def _after_next(storage, methods, action):
    """Run *action* once, right after *storage*'s next call of one of *methods*."""
    for name in methods:
        real = getattr(storage, name)

        def hooked(*args, _real=real, **kwargs):
            result = _real(*args, **kwargs)
            if not storage.__dict__.get("_fired"):
                storage._fired = True
                action()
            return result

        setattr(storage, name, hooked)


def _finisher(publisher):
    def finish():
        publisher.publish(_final("a"), final=True)
        assert publisher.close(10)
    return finish


def test_a_local_beat_that_read_before_the_winners_finish_keeps_it(root):
    a = RunStatePublisher(_local(root), APP, X)
    b_side = _local(root)
    b = RunStatePublisher(b_side, APP, X)
    a.publish(_running(0, "a"))
    b.publish(_running(0, "b"))
    b.publish(_running(1, "b"), heartbeat=True)

    _before_next(b_side, ("save_file", "save_file_if_match"), _finisher(a))
    b.publish(_running(2, "b"), heartbeat=True)

    assert load_run_state(_local(root), APP, X) == _final("a")
    assert b.superseded


@pytest.fixture
def bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        assert s3_storage().create_exclusive(APP, X, meta(X), {})
        yield


def _until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def _remote_holds(state):
    _until(lambda: load_run_state(s3_storage(), APP, X) == state)


def test_a_remote_beat_that_read_before_the_winners_finish_keeps_it(bucket):
    a, b_side = RunStatePublisher(s3_storage(), APP, X), s3_storage()
    b = RunStatePublisher(b_side, APP, X)
    b.publish(_running(0, "b"))
    _remote_holds(_running(0, "b"))
    a.publish(_running(0, "a"))  # b's token is stale now: its next beat reads
    _remote_holds(_running(0, "a"))

    def finish():
        a.publish(_final("a"), final=True)
        _remote_holds(_final("a"))

    _after_next(b_side, ("load_file", "load_file_with_token"), finish)
    b.publish(_running(1, "b"), heartbeat=True)
    assert b.close(10) and a.close(10)

    assert load_run_state(s3_storage(), APP, X) == _final("a")
    assert b.superseded


def test_a_resumed_attempts_first_write_keeps_a_finish_landing_before_it(root):
    a = Run(_local(root), APP, X, 3600)
    a._open()
    prior = load_run_state(_local(root), APP, X)
    b_side = _local(root)
    b = Run(b_side, APP, X, 3600, prior_state=prior)

    _before_next(b_side, ("save_file", "save_file_if_match"), lambda: a.finish(0))
    b._open()
    try:
        state = load_run_state(_local(root), APP, X)
        assert (state["state"], state["exit_code"]) == ("finished", 0)
        assert b.finish(1) is False
        assert load_run_state(_local(root), APP, X)["exit_code"] == 0
    finally:
        b.detach()


def test_resuming_a_finished_run_still_reopens_it(root):
    a = Run(_local(root), APP, X, 3600)
    a._open()
    a.finish(0)

    b = Run(_local(root), APP, X, 3600, prior_state=load_run_state(_local(root), APP, X))
    b._open()
    try:
        assert load_run_state(_local(root), APP, X)["state"] == "running"
    finally:
        assert b.finish(0) is True


class _CountingRemote:
    """An in-memory remote with version tokens, counting its state calls."""

    def __init__(self):
        self.data, self.version, self.calls = None, 0, []

    def is_remote(self):
        return True

    def load_file_with_token(self, app_name, verstr, filename):
        self.calls.append("get")
        return self.data, str(self.version)

    def load_file(self, app_name, verstr, filename):
        return self.load_file_with_token(app_name, verstr, filename)[0]

    def save_file_if_match(self, app_name, verstr, filename, data, etag=None):
        self.calls.append("conditional put" if etag else "put")
        if etag and etag != str(self.version):
            return False, None
        self.data, self.version = data, self.version + 1
        return True, str(self.version)

    def save_file(self, *args):
        self.calls.append("unconditional put")
        return self.save_file_if_match(*args)[0]


def test_a_steady_remote_beat_is_one_conditional_put_and_no_get():
    remote = _CountingRemote()
    publisher = RunStatePublisher(remote, APP, X)
    for seq in range(12):
        if seq == 2:
            remote.calls.clear()
        publisher.publish(_running(seq, "mine"), heartbeat=seq > 0)
        _until(lambda: remote.data and yaml.safe_load(remote.data)["heartbeat_seq"] == seq)
    assert publisher.close(10)

    assert remote.calls == ["conditional put"] * 10
