"""Plan 28 FS: ``vmn-exp list --sort`` takes a row field, ``tags.<k>`` or
``params.<k>`` too, without warning that no run logs such a metric."""
from vmn_exp.cli import experiment


def _rows():
    return [{"idx": i, "verstr": f"v{i}", "metrics": {}, "duration_sec": d,
             "tags": {"kind": k}} for i, (d, k) in enumerate([(30, "b"), (None, "a"), (5, "c")])]


def test_list_sorts_by_a_row_field_without_a_missing_metric_warning(monkeypatch):
    warnings = []
    monkeypatch.setattr(experiment, "VMN_LOGGER", type("Log", (), {"warning": warnings.append}))
    by_duration = experiment._list_rows(_rows(), None, "duration_sec", {})
    assert [r["idx"] for r in by_duration] == [2, 0, 1]
    by_kind = experiment._list_rows(_rows(), None, "tags.kind", {})
    assert [r["idx"] for r in by_kind] == [1, 0, 2]
    assert warnings == []
    experiment._list_rows(_rows(), None, "no_such_metric", {})
    assert len(warnings) == 1
