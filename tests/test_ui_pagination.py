"""Tests for experiment list pagination."""
import pytest
from version_stamp.ui.readers.experiments import sort_rows


def _make_rows(n):
    """Create n dummy experiment rows with incrementing metrics."""
    return [
        {
            "idx": i + 1,
            "verstr": f"1.0.0-dev.{i:04d}",
            "code_verstr": f"1.0.0-dev.{i:04d}",
            "timestamp": f"2025-01-{(i % 28) + 1:02d}T00:00:00",
            "note": f"run {i}",
            "branch": "master",
            "base_version": "1.0.0",
            "user_meta": None,
            "metrics": {"loss": 1.0 - i * 0.001, "acc": 0.5 + i * 0.001},
        }
        for i in range(n)
    ]


class TestSortRowsPagination:
    def test_without_pagination_returns_list(self):
        rows = _make_rows(10)
        result = sort_rows(rows, {}, sort=None, last=None)
        assert isinstance(result, list)
        assert len(result) == 10

    def test_with_limit_returns_dict(self):
        rows = _make_rows(50)
        result = sort_rows(rows, {}, sort=None, last=None, limit=10)
        assert isinstance(result, dict)
        assert len(result["rows"]) == 10
        assert result["total"] == 50

    def test_offset_and_limit(self):
        rows = _make_rows(50)
        result = sort_rows(rows, {}, sort=None, last=None, offset=10, limit=10)
        assert isinstance(result, dict)
        assert len(result["rows"]) == 10
        assert result["total"] == 50
        assert result["rows"][0]["verstr"] == rows[10]["verstr"]

    def test_offset_beyond_total(self):
        rows = _make_rows(10)
        result = sort_rows(rows, {}, sort=None, last=None, offset=20, limit=5)
        assert isinstance(result, dict)
        assert len(result["rows"]) == 0
        assert result["total"] == 10

    def test_limit_larger_than_remaining(self):
        rows = _make_rows(10)
        result = sort_rows(rows, {}, sort=None, last=None, offset=8, limit=5)
        assert isinstance(result, dict)
        assert len(result["rows"]) == 2
        assert result["total"] == 10

    def test_sort_with_pagination(self):
        rows = _make_rows(50)
        schema = {"loss": {"goal": "min"}}
        result = sort_rows(rows, schema, sort="loss", last=None, limit=5)
        assert isinstance(result, dict)
        assert result["total"] == 50
        sorted_rows = result["rows"]
        for i in range(len(sorted_rows) - 1):
            assert sorted_rows[i]["metrics"]["loss"] <= sorted_rows[i + 1]["metrics"]["loss"]

    def test_backward_compat_no_limit(self):
        rows = _make_rows(10)
        result = sort_rows(rows, {})
        assert isinstance(result, list)
