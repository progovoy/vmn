"""Every reader of a local root folds a log again once a local-first cache over
that root rewrote it (a merge of the remote's lines, :mod:`cached_log_merge`),
not only a reader with a remote: an offline one (``VMN_EXP_OFFLINE``, a local
root and no remote) persists to the same index file as the online one, and a
``vmn-exp ui`` lists a local root in its I/O helper process. Each one's rows,
also after a reload from the persisted index, equal a full read.
"""
import pytest
from s3_helpers import cached_host, meta
from test_index_log_rewrite import LONG, _host_a_shipped, _params, bucket  # noqa: F401
from test_storage_cached_log_seed import _note
from test_storage_cached_log_seed_failed import _remote_listing_fails_once
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.snapshot import open_storage

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
W = "w"


def _tags(second, **tags):
    return {"timestamp": f"2026-01-01T00:00:{second:02d}Z", "type": "tags", "set": tags}


def _offline(tmp_path, root):
    """*root*'s storage under ``VMN_EXP_OFFLINE``: the local root alone."""
    return open_storage(None, root=str(tmp_path / root), area="runs")


def _rows(storage, cache, io_process=False):
    """One process's ``vmn-exp list`` (or ``vmn-exp ui`` refresh) over *cache*."""
    index = ExperimentIndex(storage, APP, cache_path=cache)
    try:
        if io_process:
            assert index.use_io_process()
        return index.refresh().rows()
    finally:
        index.close()


def _assert_offline_rows_match(tmp_path, cache, io_process=False):
    storage = _offline(tmp_path, "b")
    truth = direct_rows(storage, APP)[0]
    assert _rows(storage, cache, io_process) == truth
    assert _rows(_offline(tmp_path, "b"), cache, io_process) == truth  # persisted
    return truth


def _merged_after_a_failed_seed(tmp_path, cache, io_process=False):
    """Clone b's seed fails, an offline list folds its local copy, then an
    online append on b merges the remote's lines into it."""
    _host_a_shipped(tmp_path, _params(0, lr=0.1, layers=4))
    b = cached_host(tmp_path, "b")
    _remote_listing_fails_once(b)
    assert b.append_log_entry(APP, V, W, _note(LONG, 10))  # the local copy: LONG only
    _rows(_offline(tmp_path, "b"), cache, io_process)

    online = cached_host(tmp_path, "b")
    assert online.append_log_entry(APP, V, W, _tags(11, k="v"))
    online.sync_log_to_remote(APP, V, W)  # merges: the remote's lines, then b's


@pytest.mark.parametrize("io_process", [False, True], ids=["in-process", "io-helper"])
def test_an_offline_reader_refolds_a_log_an_online_cache_merged_after_a_failed_seed(
    tmp_path, bucket, io_process  # noqa: F811
):
    cache = str(tmp_path / "idx.sqlite")
    _merged_after_a_failed_seed(tmp_path, cache, io_process)

    truth = _assert_offline_rows_match(tmp_path, cache, io_process)
    assert truth[0]["params"] == {"lr": 0.1, "layers": 4}
    assert truth[0]["tags"] == {"k": "v"}


@pytest.mark.parametrize("io_process", [False, True], ids=["in-process", "io-helper"])
def test_an_offline_reader_refolds_a_log_an_online_seed_rewrote(
    tmp_path, bucket, io_process  # noqa: F811
):
    """Two clones on one host share a writer id; no remote call fails."""
    cache = str(tmp_path / "idx.sqlite")
    a = cached_host(tmp_path, "a")
    a.save(APP, V, meta(V), {})
    assert a.append_log_entry(APP, V, W, _params(0, lr=0.1, layers=4))
    a.sync_log_to_remote(APP, V, W)
    b = cached_host(tmp_path, "b")
    assert b.append_log_entry(APP, V, W, _tags(1, t0="x"))  # seeded from the remote
    b.sync_log_to_remote(APP, V, W)
    a = cached_host(tmp_path, "a")
    assert a.append_log_entry(APP, V, W, _tags(2, n1="y" * 500))
    a.sync_log_to_remote(APP, V, W)

    assert _offline(tmp_path, "b").append_log_entry(APP, V, W, _tags(3, t2="z"))
    _rows(_offline(tmp_path, "b"), cache, io_process)
    b = cached_host(tmp_path, "b")
    assert b.append_log_entry(APP, V, W, _tags(4, t3="w"))  # the seed rewrites b's copy
    b.sync_log_to_remote(APP, V, W)

    truth = _assert_offline_rows_match(tmp_path, cache, io_process)
    assert sorted(truth[0]["tags"]) == ["n1", "t0", "t2", "t3"]
