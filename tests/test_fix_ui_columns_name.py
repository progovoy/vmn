"""The ``name`` column of ``.../experiments-columns`` is the run name."""
import pytest

pytest.importorskip("fastapi")

from version_stamp.core.experiment_log import experiment_row
from version_stamp.ui.leaderboard_columns import columns_payload


def _row(idx, **meta):
    return experiment_row(idx, dict({"verstr": f"1.0.0-dev.r{idx}"}, **meta), [])


def test_the_name_column_reads_the_run_name():
    rows = [_row(1, name="lr-sweep", note="a note"), _row(2, name="baseline")]
    assert columns_payload(rows, ["name"], 2)["columns"]["name"] == ["lr-sweep", "baseline"]


def test_an_unnamed_run_falls_back_to_its_note():
    rows = [_row(1, note="only a note"), _row(2)]
    assert columns_payload(rows, ["name"], 2)["columns"]["name"] == ["only a note", None]
