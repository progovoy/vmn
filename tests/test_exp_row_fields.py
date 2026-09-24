"""Row fields for run names, tags and archiving, and their query support.

``name`` and ``archived`` come from ``metadata.yml``; ``tags`` fold from
``tags`` log entries (last write wins per key, removal supported). The direct
fold and the incremental index agree, and the query language reads all three.
"""
import datetime
import os

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core.experiment_fold import apply_entries, fold_row, new_fold
from version_stamp.core.experiment_index import ExperimentIndex
from version_stamp.core.experiment_log import experiment_row, filter_archived
from version_stamp.core.experiment_query import QueryError, filter_rows
from version_stamp.core.experiment_writer import create_tags_entry

META = {"verstr": "0.0.1-dev.a", "timestamp": "2026-01-01T00:00:00Z"}


def _tags(ts, set_=None, remove=None):
    entry = create_tags_entry(set_, remove)
    entry["timestamp"] = ts
    return entry


def test_row_carries_name_and_archived_from_metadata():
    row = experiment_row(1, dict(META, name="baseline", archived=True), [])
    assert row["name"] == "baseline"
    assert row["archived"] is True


def test_unnamed_unarchived_row_defaults():
    row = experiment_row(1, META, [])
    assert row["name"] is None
    assert row["archived"] is False
    assert row["tags"] == {}


def test_tags_fold_last_write_wins_and_removal():
    log = [
        _tags("t1", {"stage": "dev", "owner": "ann"}),
        _tags("t2", {"stage": "prod"}),
        _tags("t3", remove=["owner"]),
    ]
    assert experiment_row(1, META, log)["tags"] == {"stage": "prod"}


def test_a_removed_tag_can_be_set_again():
    log = [_tags("t1", {"k": "a"}), _tags("t2", remove=["k"]), _tags("t3", {"k": "b"})]
    assert experiment_row(1, META, log)["tags"] == {"k": "b"}


def test_tag_values_are_stored_as_strings():
    entry = create_tags_entry({"epochs": 10, "gpu": True})
    assert entry["type"] == "tags"
    assert entry["set"] == {"epochs": "10", "gpu": "True"}


@pytest.mark.parametrize("bad", ["", None, 3])
def test_tag_keys_must_be_non_empty_strings(bad):
    with pytest.raises(ValueError):
        create_tags_entry({bad: "v"})


def test_an_empty_tags_entry_is_refused():
    with pytest.raises(ValueError):
        create_tags_entry({}, [])


def test_create_entry_tags_seed_the_row():
    log = [{"timestamp": "t0", "type": "create", "tags": {"team": "nlp"}}]
    assert experiment_row(1, META, log)["tags"] == {"team": "nlp"}


def test_index_fold_by_writer_matches_the_direct_fold():
    a = [_tags("t1", {"k": "a"}), _tags("t3", remove=["k"])]
    b = [_tags("t2", {"k": "b", "x": "1"})]
    fold = apply_entries(apply_entries(new_fold(), "wa", 0, a), "wb", 0, b)
    merged = sorted(a + b, key=lambda e: e["timestamp"])
    assert fold_row(1, META, fold)["tags"] == experiment_row(1, META, merged)["tags"]


def test_filter_archived_hides_archived_rows_by_default():
    rows = [{"verstr": "a", "archived": False}, {"verstr": "b", "archived": True}]
    assert [r["verstr"] for r in filter_archived(rows)] == ["a"]
    assert filter_archived(rows, include_archived=True) == rows


ROWS = [
    dict(experiment_row(1, dict(META, name="lr-sweep-1"), [_tags("t", {"stage": "prod"})])),
    dict(experiment_row(2, dict(META, verstr="0.0.1-dev.b", archived=True), [])),
]


def test_query_filters_on_name():
    assert [r["idx"] for r in filter_rows(ROWS, 'name ~ "sweep"')] == [1]
    assert [r["idx"] for r in filter_rows(ROWS, "name = null")] == [2]


def test_query_filters_on_tags():
    assert [r["idx"] for r in filter_rows(ROWS, 'tags.stage = "prod"')] == [1]
    assert [r["idx"] for r in filter_rows(ROWS, 'tags.stage != "prod"')] == [2]


def test_query_filters_on_archived():
    assert [r["idx"] for r in filter_rows(ROWS, "archived = true")] == [2]
    assert [r["idx"] for r in filter_rows(ROWS, "archived = false")] == [1]


def test_query_still_rejects_unknown_prefixes():
    with pytest.raises(QueryError):
        filter_rows(ROWS, 'labels.stage = "prod"')


# ---------------------------------------------------------------------------
# the index: rows and the run state's storage-observed time
# ---------------------------------------------------------------------------


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "repo"), subdir="experiments")


def _index(st, tmp_path):
    return ExperimentIndex(st, "app", cache_path=str(tmp_path / "idx.sqlite"))


def test_index_rows_carry_name_tags_and_archived(st, tmp_path):
    st.save("app", "v1", {"verstr": "v1", "timestamp": "t", "name": "n1"}, {})
    st.append_log_entry("app", "v1", "w", _tags("t1", {"k": "v"}))
    st.update_metadata("app", "v1", {"archived": True})

    row = _index(st, tmp_path).refresh().rows()[0]

    assert (row["name"], row["tags"], row["archived"]) == ("n1", {"k": "v"}, True)


def test_snapshot_exposes_when_storage_saw_each_run_state(st, tmp_path):
    st.save("app", "v1", {"verstr": "v1", "timestamp": "t1"}, {})
    st.save("app", "v2", {"verstr": "v2", "timestamp": "t2"}, {})
    st.save_file("app", "v1", "run_state.yml", "state: running\n")
    os.utime(os.path.join(st._snapshot_dir("app", "v1"), "run_state.yml"), (1e9, 1e9))

    snap = _index(st, tmp_path).refresh().snapshot()

    expected = datetime.datetime.fromtimestamp(1e9, tz=datetime.timezone.utc)
    assert snap.run_state_observed_at["v1"] == expected
    assert snap.run_state_observed_at["v2"] is None
