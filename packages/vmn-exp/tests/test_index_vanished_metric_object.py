"""A metric object that vanishes between a refresh's listing and its read
never fails the refresh. A live run's owner rolls its segments into a wider
``.vmx`` (``@000000-000012``) and deletes the one before (``@000000-000011``);
a client's refresh that had listed the old name read None for it, and
``MetricIndexReader`` raised ``TypeError: 'NoneType' object is not
subscriptable`` — every retry the same, so the index stopped updating at
145,761 of 576k runs. The index lists the record afresh and folds what is
there now. And any record that still fails to read is set aside and retried
later instead of failing the whole refresh."""
import pytest
from s3_helpers import meta
from test_index_metric_reads_s3 import APP, V, _index, _live_run, _put_rollup, _row, s3  # noqa: F401
import vmn_exp.core.index as index_module


def _swap_after_listing(index, storage, covers):
    """Once the index has listed the record, the owner rolls up to *covers*
    (deleting the ``.vmx`` the listing named)."""
    listing = index._storage.list_files
    done = []

    def list_files(*args, **kwargs):
        listed = listing(*args, **kwargs)
        if not done:
            done.append(True)
            _put_rollup(storage, covers)
        return listed

    index._storage.list_files = list_files
    between = getattr(index._storage, "list_files_between", None)
    if between is not None:
        def list_files_between(*args, **kwargs):
            listed = between(*args, **kwargs)
            if not done:
                done.append(True)
                _put_rollup(storage, covers)
            return listed
        index._storage.list_files_between = list_files_between


def test_a_vmx_replaced_after_the_listing_is_folded_from_a_fresh_listing(s3, tmp_path):
    _live_run(s3, segments=13)
    _put_rollup(s3, covers=11)
    index = _index(tmp_path)
    _swap_after_listing(index, s3, covers=12)

    got = _row(index)  # no exception

    assert got == _row(_index(tmp_path, "fresh.sqlite"))


def test_a_record_that_fails_to_read_is_set_aside_not_the_refresh(s3, tmp_path, monkeypatch):
    bad = "1.0.0-dev.b"
    s3.save(APP, bad, meta(bad), {})
    real = index_module.refresh_record
    failing = [True]

    def refresh_record(key, *args, **kwargs):
        if key == bad and failing[0]:
            raise TypeError("'NoneType' object is not subscriptable")
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    index = _index(tmp_path)

    rows = index.refresh().rows()  # no exception

    assert [r["verstr"] for r in rows] == [V]
    failing[0] = False
    monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 0)
    assert sorted(r["verstr"] for r in index.refresh().rows()) == sorted([V, bad])
