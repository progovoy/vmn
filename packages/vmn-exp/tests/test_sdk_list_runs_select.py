"""``list_runs`` row selection and its loading check (plan 41 D9): ``limit``
keeps the best N after sorting, ``last`` the newest N before it,
``descending`` forces the direction, and rows of an index still loading
raise unless the caller asks for them with ``incomplete="warn"``."""
import dataclasses
import os

import pytest

import vmn_exp.core.index as experiment_index
from vmn_exp.core.load_progress import IndexingWarning
from vmn_exp.sdk import reader
from vmn_exp.sdk.reader_select import check_loading, select
from vmn_exp.storage.local import LocalSnapshotStorage

SCHEMA = {"loss": {"goal": "min"}}
PROGRESS = "indexing 120k/734k runs — results incomplete"


def _rows(*losses):
    return [{"verstr": f"r{i}", "idx": i, "metrics": {"loss": v}} for i, v in enumerate(losses)]


def _names(rows):
    return [r["verstr"] for r in rows]


def test_limit_takes_the_best_n_after_sorting():
    rows = _rows(0.9, 0.1, 0.5, 0.3)
    assert _names(select(rows, SCHEMA, sort="loss", limit=2)) == ["r1", "r3"]


def test_last_still_slices_before_sorting():
    rows = _rows(0.1, 0.9, 0.5, 0.3)
    assert _names(select(rows, SCHEMA, sort="loss", last=2)) == ["r3", "r2"]


def test_descending_forces_the_metric_direction():
    rows = _rows(0.9, 0.1, 0.5)
    assert _names(select(rows, SCHEMA, sort="loss", descending=True)) == ["r0", "r2", "r1"]


@pytest.mark.parametrize("limit", [0, -1, 1.5, "3", True])
def test_limit_must_be_a_positive_int(limit):
    with pytest.raises(ValueError, match="limit"):
        select(_rows(0.1), SCHEMA, limit=limit)


def test_incomplete_raise_raises_indexing_warning_with_the_progress_text():
    with pytest.raises(IndexingWarning, match=PROGRESS):
        check_loading((120_000, 734_000), "raise", stacklevel=1)


def test_incomplete_warn_keeps_the_warning_text_unchanged():
    with pytest.warns(IndexingWarning) as caught:
        check_loading((120_000, 734_000), "warn", stacklevel=1)
    assert [str(w.message) for w in caught] == [PROGRESS]


def test_incomplete_not_passed_raises_and_says_how_to_keep_partial_rows():
    with pytest.raises(IndexingWarning, match=PROGRESS) as raised:
        check_loading((120_000, 734_000), None, stacklevel=1)
    assert 'incomplete="warn"' in str(raised.value)


def test_a_loaded_index_neither_warns_nor_raises():
    check_loading(None, None, stacklevel=1)


@pytest.mark.parametrize("incomplete", ["ignore", True, "WARN"])
def test_unknown_incomplete_value_is_a_value_error(incomplete):
    with pytest.raises(ValueError, match="incomplete"):
        check_loading(None, incomplete, stacklevel=1)


def test_the_warning_points_at_the_caller_of_list_runs(tmp_path, monkeypatch):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    storage.save("app", "1.0.0-dev.a", {"verstr": "1.0.0-dev.a", "timestamp": "2026-01-01T00:00:00Z"}, {})
    real = experiment_index.indexed_snapshot
    monkeypatch.setattr(experiment_index, "indexed_snapshot", lambda *a, **k: dataclasses.replace(
        real(*a, **k), loading=(1, 2)))
    with pytest.warns(IndexingWarning) as caught:
        reader.list_runs("app", storage=storage, incomplete="warn")
    assert os.path.basename(caught[0].filename) == os.path.basename(__file__)
