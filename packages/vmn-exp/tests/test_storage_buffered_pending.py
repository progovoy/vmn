"""A buffered storage tells what an earlier ship left behind and ships it on
request (plan 40 C16: the UI server retries a failed edit before the next
action on its workspace)."""
import tempfile

import pytest
from s3_helpers import entry, meta, mocked_bucket, s3_storage

from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage

APP, V, W = "app", "v", "w"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with mocked_bucket(monkeypatch):
        yield
        buffered.close_all()


@pytest.fixture
def pod(tmp_path):
    remote = s3_storage()
    remote.save(APP, V, meta(V), {})
    return BufferedRemoteStorage(remote, str(tmp_path), area="runs")


def _unreachable(*args, **kwargs):
    raise ConnectionError("the store is out of reach")


def _remote_steps():
    return [e["values"]["i"] for e in s3_storage().load_merged_log(APP, V)]


def _append_while_cut_off(monkeypatch, pod):
    with monkeypatch.context() as m:
        m.setattr(pod, "_ship", _unreachable)
        pod.append_log_entry(APP, V, W, entry(0))
        with pytest.raises(ConnectionError):
            pod.sync_log_to_remote(APP, V, W)  # what flush_log does next


def test_nothing_is_pending_after_a_ship_that_went_through(pod):
    pod.append_log_entry(APP, V, W, entry(0))
    assert not pod.has_pending()
    assert _remote_steps() == [0]


def test_an_append_whose_ship_failed_is_pending(monkeypatch, pod):
    _append_while_cut_off(monkeypatch, pod)
    assert pod.has_pending()
    assert _remote_steps() == []


def test_ship_pending_ships_it_once_the_store_answers(monkeypatch, pod):
    _append_while_cut_off(monkeypatch, pod)
    pod.ship_pending()
    assert not pod.has_pending()
    assert _remote_steps() == [0]


def test_ship_pending_raises_while_the_store_still_fails(monkeypatch, pod):
    _append_while_cut_off(monkeypatch, pod)
    monkeypatch.setattr(pod, "_ship", _unreachable)
    with pytest.raises(ConnectionError):
        pod.ship_pending()
    assert pod.has_pending()
