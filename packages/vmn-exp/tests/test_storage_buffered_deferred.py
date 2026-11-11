"""A run that defers its ships (plan 40 C3) is asked to ship when a ship is
due, instead of the append shipping on the appending thread."""
import tempfile

import pytest
from deferred_ship_fakes import FakeBucket
from s3_helpers import entry, meta

from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage

APP, V, OTHER, W = "app", "v", "other", "w"


@pytest.fixture(autouse=True)
def _temp(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "buffers"))
    (tmp_path / "buffers").mkdir()
    yield
    buffered.close_all()


@pytest.fixture
def bucket(tmp_path):
    remote = FakeBucket(str(tmp_path / "bucket"))
    for verstr in (V, OTHER):
        remote.save(APP, verstr, meta(verstr), {})
    return remote


@pytest.fixture
def pod(bucket, tmp_path):
    return BufferedRemoteStorage(bucket, str(tmp_path / "buffers"), area="runs")


class _Requests:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def _block(value):
    return encode_block({"x": Columns([0], [0], [value])})


def test_a_due_append_with_a_requester_asks_instead_of_shipping(pod, bucket):
    request = _Requests()
    pod.defer_ships(APP, V, request)

    assert pod.append_log_entry(APP, V, W, entry(0))  # the first is due at once

    assert bucket.creates == 0
    assert request.calls == 1
    assert pod.has_pending()


def test_a_due_metric_block_with_a_requester_asks_instead_of_shipping(pod, bucket):
    request = _Requests()
    pod.defer_ships(APP, V, request)

    assert pod.append_metric_block(APP, V, W, _block(1.0))

    assert bucket.creates == 0
    assert request.calls == 1
    assert pod.has_pending()


def test_the_requested_ship_ships_what_was_deferred(pod, bucket):
    pod.defer_ships(APP, V, _Requests())
    pod.append_log_entry(APP, V, W, entry(0))

    pod.sync_log_to_remote(APP, V, W)  # what the run's worker does

    assert bucket.creates == 1
    assert not pod.has_pending()


def test_appends_of_another_run_still_ship_inline(pod, bucket):
    request = _Requests()
    pod.defer_ships(APP, V, request)

    pod.append_log_entry(APP, OTHER, W, entry(0))
    pod.append_metric_block(APP, OTHER, W, _block(1.0))

    assert bucket.creates == 2
    assert request.calls == 0


def test_undeferring_restores_inline_shipping(pod, bucket):
    request = _Requests()
    pod.defer_ships(APP, V, request)
    pod.undefer_ships(APP, V)

    pod.append_log_entry(APP, V, W, entry(0))

    assert bucket.creates == 1
    assert request.calls == 0


def test_a_forked_childs_buffer_has_no_requesters(pod, bucket):
    request = _Requests()
    pod.defer_ships(APP, V, request)

    pod._start_child_buffer()  # what a forked child's first touch does
    pod.append_log_entry(APP, V, W, entry(0))

    assert request.calls == 0
    assert bucket.creates == 1
