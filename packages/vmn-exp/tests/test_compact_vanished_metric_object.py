"""A metric object that vanishes between a compaction's listing and its read
never fails the compaction. Another compactor (a second server on the store,
or the live run's owner) rolled the stream into a wider ``.vmx`` and deleted
the one the listing named; ``read_range`` answered None for it and
``MetricIndexReader`` raised ``TypeError: 'NoneType' object is not
subscriptable`` from store upkeep. The read raises ``MetricObjectGone``; a
compaction lists the stream again once, and a chart read reads the run again."""
import random

import pytest
from test_series_reader import APP, V, _entries, _storage, _write

from vmn_exp.core.index_metric_reads import MetricObjectGone
from vmn_exp.core.metric_compact import compact_record, compact_writer
from vmn_exp.core.metric_files import indexed_name, is_indexed_file
from vmn_exp.core.series_reader import writer_source

GHOST = indexed_name("w", 99)


class _Vanishing:
    """*storage* whose first *stale* metric listings name :data:`GHOST`, a
    ``.vmx`` already deleted: reading it answers None."""

    def __init__(self, storage, stale=1):
        self._storage, self.stale = storage, stale

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def metric_objects(self, app_name, verstr):
        objects = self._storage.metric_objects(app_name, verstr)
        if self.stale:
            self.stale -= 1
            objects = {w: [(GHOST, 4096)] + objs for w, objs in objects.items()}
        return objects

    def read_range(self, app_name, verstr, name, offset, length):
        if name == GHOST:
            return None
        return self._storage.read_range(app_name, verstr, name, offset, length)


def _stored(tmp_path):
    storage = _storage(tmp_path)
    _write(storage, "w", _entries(random.Random(3), 50, 1_700_000_000_000_000))
    return storage


def _compacted(storage):
    return all(is_indexed_file(n) for n, _ in storage.metric_objects(APP, V)["w"])


def test_a_vanished_vmx_reads_as_metric_object_gone(tmp_path):
    storage = _Vanishing(_stored(tmp_path))
    with pytest.raises(MetricObjectGone):
        writer_source(storage, APP, V, [(GHOST, 4096)])


def test_a_vanished_segment_reads_as_metric_object_gone(tmp_path):
    storage = _Vanishing(_stored(tmp_path))
    with pytest.raises(MetricObjectGone):
        writer_source(storage, APP, V, [("metrics/w@000005.vms", 10)]).counts()


def test_compaction_lists_the_stream_again_when_its_vmx_vanished(tmp_path):
    storage = _Vanishing(_stored(tmp_path))
    assert compact_writer(storage, APP, V, "w")
    assert _compacted(storage)


def test_compaction_vanished_twice_is_not_compacted_and_does_not_raise(tmp_path):
    storage = _Vanishing(_stored(tmp_path), stale=2)
    assert compact_writer(storage, APP, V, "w") is False
    assert compact_record(_Vanishing(storage._storage, stale=3), APP, V) == []


def test_store_upkeep_counts_a_vanished_vmx_as_no_failure(tmp_path):
    from test_ui_store_upkeep import _run, _snap

    from vmn_exp.storage.local import LocalSnapshotStorage
    from vmn_exp.ui.store_upkeep import AppUpkeep

    local = LocalSnapshotStorage(str(tmp_path / "root"), area="runs")
    failed = _run(local, exit_code=1)
    storage = _Vanishing(local, stale=0)
    snapshot = _snap(local)
    storage.stale = 2  # compact_record's listing and compact_writer's

    counts = AppUpkeep(storage, "my_app").run(snapshot)

    assert counts["failed"] == 0 and counts["compacted"] == 1
    assert all(is_indexed_file(n) for objs in local.metric_objects("my_app", failed).values()
               for n, _ in objs)


def test_a_chart_read_reads_the_run_again_when_its_vmx_vanished(tmp_path):
    from vmn_exp.ui.readers.range_series import read_run

    storage = _Vanishing(_stored(tmp_path))
    log, reader = read_run(storage, APP, V)
    assert reader.keys()


def test_the_log_view_reads_the_run_again_when_a_metric_object_vanished(tmp_path):
    from vmn_exp.storage.files import merged_log

    stored = _stored(tmp_path)
    expected = merged_log(stored, APP, V, {})
    assert repr(merged_log(_Vanishing(stored), APP, V, {})) == repr(expected)  # NaN-safe
