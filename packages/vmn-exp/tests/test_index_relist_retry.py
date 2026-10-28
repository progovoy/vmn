"""A listing behind serving survives a store that refuses some of its
requests (S3 ``SlowDown`` past botocore's retries): a chunk that fails is
retried, and one that keeps failing is listed later as hints, so the listing
goes on. The first error used to end it, and the next refresh started a new
one from the record names — under sustained throttling it never finished."""
import threading

import pytest

from journal_index_helpers import APP, Spy, make, settle, storage, verstrs
from vmn_exp.core import index_relist
from vmn_exp.core.index import ExperimentIndex


class Refused(Exception):
    """The store refusing a request."""


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setattr(index_relist, "LISTING_CHUNK", 5)
    monkeypatch.setattr(index_relist, "LISTING_WORKERS", 2)
    monkeypatch.setattr(index_relist, "RETRY_SEC", 0)
    return storage(tmp_path)


def _journaled(st):
    index = ExperimentIndex(st, APP, full_sweep_sec=3600)
    index.journaled = True
    return index


def _refuse(st, spy, monkeypatch, key, times):
    """The next *times* keyed listings of *key* raise."""
    left, lock = [times], threading.Lock()

    def list_files(app_name, keys=None, **kw):
        with lock:
            refused = keys is not None and key in keys and left[0] > 0
            left[0] -= refused
        if refused:
            raise Refused(key)
        return spy.list_files(app_name, keys=keys, **kw)

    monkeypatch.setattr(st, "list_files", list_files)


def test_a_chunk_refused_once_is_retried_and_the_cold_listing_goes_on(st, monkeypatch):
    runs = {make(st, i) for i in range(20)}
    spy = Spy(st, monkeypatch)
    _refuse(st, spy, monkeypatch, "0.0.1-dev.abc.r7", 1)

    index = settle(_journaled(st))

    assert verstrs(index) == runs
    assert spy.names == 1


def test_a_chunk_refused_past_its_retries_is_listed_later(st, monkeypatch):
    runs = {make(st, i) for i in range(20)}
    spy = Spy(st, monkeypatch)
    _refuse(st, spy, monkeypatch, "0.0.1-dev.abc.r7", index_relist.LISTING_ATTEMPTS)

    index = settle(_journaled(st))

    assert verstrs(index) == runs
    assert spy.names == 1


def test_a_reconcile_whose_chunk_is_refused_is_not_restarted(st, monkeypatch):
    runs = {make(st, i) for i in range(20)}
    spy = Spy(st, monkeypatch)
    index = settle(_journaled(st))
    runs.add(make(st, 30))
    spy.reset()
    _refuse(st, spy, monkeypatch, "0.0.1-dev.abc.r12", 1)

    index.reconcile()
    settle(index)

    assert verstrs(index) == runs
    assert spy.names == 1


def test_a_names_listing_refused_once_is_retried(st, monkeypatch):
    runs = {make(st, i) for i in range(8)}
    spy = Spy(st, monkeypatch)
    left, real = [1], spy.list_record_names

    def list_record_names(app_name):
        if left[0]:
            left[0] -= 1
            raise Refused("names")
        return real(app_name)

    monkeypatch.setattr(st, "list_record_names", list_record_names)

    index = settle(_journaled(st))

    assert verstrs(index) == runs
    assert spy.names == 1
