"""Archive by query: ``manage.archive_runs`` / ``manage.unarchive_runs``.

The runs ``list_runs(query=...)`` selects are archived in one call, with the
writes spread over threads; a run already in the wanted state is skipped, and
a dry run only reports.
"""
import pytest

from vmn_exp.core.query import QueryError
from vmn_exp.sdk import manage, reader
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTRS = [f"0.0.1-dev.aaaaaa{i}.bbbbbbb" for i in range(5)]


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    for i, verstr in enumerate(VERSTRS):
        st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        manage.set_tags(APP, verstr, {"batch": "old" if i % 2 else "new"}, storage=st)
    return st


def _archived(storage):
    return sorted(v for v in VERSTRS if storage.load_metadata(APP, v).get("archived"))


def _old():
    return sorted(VERSTRS[1::2])


def test_archive_runs_archives_exactly_the_matching_runs(storage):
    done = manage.archive_runs(APP, 'tags.batch = "old"', storage=storage)

    assert sorted(done) == _old()
    assert _archived(storage) == _old()
    shown = [r["verstr"] for r in reader.list_runs(APP, storage=storage)]
    assert sorted(shown) == sorted(VERSTRS[0::2])


def test_archive_runs_skips_runs_already_archived(storage):
    manage.archive_run(APP, VERSTRS[1], storage=storage)

    done = manage.archive_runs(APP, 'tags.batch = "old"', storage=storage)

    assert sorted(done) == [VERSTRS[3]]
    assert _archived(storage) == _old()


def test_archive_runs_dry_run_writes_nothing(storage):
    done = manage.archive_runs(APP, 'tags.batch = "old"', storage=storage, dry_run=True)

    assert sorted(done) == _old()
    assert _archived(storage) == []


def test_unarchive_runs_unarchives_the_matching_archived_runs(storage):
    for verstr in VERSTRS:
        manage.archive_run(APP, verstr, storage=storage)

    done = manage.unarchive_runs(APP, 'tags.batch = "old"', storage=storage)

    assert sorted(done) == _old()
    assert _archived(storage) == sorted(VERSTRS[0::2])


def test_archive_runs_needs_a_valid_query(storage):
    with pytest.raises(QueryError):
        manage.archive_runs(APP, "", storage=storage)
    with pytest.raises(QueryError):
        manage.archive_runs(APP, "tags.batch ==", storage=storage)
    assert _archived(storage) == []
