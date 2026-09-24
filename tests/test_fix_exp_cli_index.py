"""`vmn exp show/compare/list` read through the experiment index — never every
record's metadata — plus `list --query` and `--json` output."""
import json
import re

import pytest
from helpers import _bootstrap, _exp, _storage

from version_stamp.cli.snapshot import LocalSnapshotStorage

_ROW_RE = re.compile(r"^\s*\[(\d+)\]\s+(\S+)")


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _three_runs(app_layout):
    _bootstrap(app_layout)
    outer = _create(app_layout, "--metrics", "loss=0.4")
    inner = _create(app_layout, "--parent", outer, "--metrics", "loss=0.2")
    last = _create(app_layout, "--metrics", "loss=0.1")
    return outer, inner, last


def _refuse_full_listing(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("read every record's metadata")

    monkeypatch.setattr(LocalSnapshotStorage, "list_snapshots", refuse)


def _run(capfd, app_layout, **kwargs):
    capfd.readouterr()
    rc = _exp(app_layout.app_name, **kwargs)
    return rc, capfd.readouterr().out


# ---------------------------------------------------------------------------
# show / compare
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["@1", None, "exact"])
def test_show_reads_no_full_listing(app_layout, capfd, monkeypatch, ref):
    outer, inner, last = _three_runs(app_layout)
    _refuse_full_listing(monkeypatch)
    version = outer if ref == "exact" else ref
    rc, out = _run(capfd, app_layout, action="show", version=version)
    assert rc == 0
    shown = last if ref is None else outer
    assert f"Experiment: {shown}" in out
    if shown == outer:
        assert f"Children:  {inner}" in out


def test_compare_last_reads_no_full_listing(app_layout, capfd, monkeypatch):
    outer, inner, last = _three_runs(app_layout)
    _refuse_full_listing(monkeypatch)
    rc, out = _run(capfd, app_layout, action="compare", last=2)
    assert rc == 0
    header = out.splitlines()[0].split()
    assert header == ["metric", inner[-20:], last[-20:]]


# ---------------------------------------------------------------------------
# list --query
# ---------------------------------------------------------------------------


def _listed(out):
    return [(int(m.group(1)), m.group(2)) for m in map(_ROW_RE.match, out.splitlines()) if m]


def test_list_query_filters_and_keeps_storage_numbers(app_layout, capfd):
    outer, inner, last = _three_runs(app_layout)
    rc, out = _run(
        capfd, app_layout, action="list", extra_args=["--query", "metrics.loss < 0.3"]
    )
    assert rc == 0
    assert _listed(out) == [(2, inner), (3, last)]


def test_list_query_sees_tree_and_status_fields(app_layout, capfd):
    outer, inner, last = _three_runs(app_layout)
    rc, out = _run(
        capfd, app_layout, action="list",
        extra_args=["--query", 'kind = "outer" and status = "created"'],
    )
    assert rc == 0
    assert _listed(out) == [(1, outer)]


def test_list_query_applies_before_last(app_layout, capfd):
    outer, inner, last = _three_runs(app_layout)
    rc, out = _run(
        capfd, app_layout, action="list", last=1,
        extra_args=["--query", "metrics.loss > 0.3"],
    )
    assert rc == 0
    assert _listed(out) == [(1, outer)]


def test_list_rejects_a_bad_query(app_layout, capfd):
    _three_runs(app_layout)
    rc, _ = _run(capfd, app_layout, action="list", extra_args=["--query", "statuz = 1"])
    assert rc == 1


# ---------------------------------------------------------------------------
# --json
# ---------------------------------------------------------------------------

LIST_KEYS = {
    "idx", "verstr", "timestamp", "note", "branch", "parent", "params", "metrics",
    "status", "exit_code", "tree_status", "kind", "depth", "children",
}


def test_list_json_is_machine_readable(app_layout, capfd):
    outer, inner, last = _three_runs(app_layout)
    rc, out = _run(capfd, app_layout, action="list", sort="loss", extra_args=["--json"])
    assert rc == 0
    rows = json.loads(out)
    assert [(r["idx"], r["verstr"]) for r in rows] == [(3, last), (2, inner), (1, outer)]
    for row in rows:
        assert LIST_KEYS <= set(row), LIST_KEYS - set(row)
    assert rows[2]["kind"] == "outer" and rows[2]["children"] == [inner]
    assert rows[0]["metrics"]["loss"] == 0.1


def test_list_json_with_query(app_layout, capfd):
    outer, inner, last = _three_runs(app_layout)
    rc, out = _run(
        capfd, app_layout, action="list",
        extra_args=["--json", "--query", f'verstr = "{inner}"'],
    )
    assert rc == 0
    assert [r["verstr"] for r in json.loads(out)] == [inner]


def test_list_json_writes_non_finite_metrics_as_null(app_layout, capfd):
    outer, _, _ = _three_runs(app_layout)
    _storage(app_layout).append_log_entry(
        app_layout.app_name, outer, "w9",
        {"timestamp": "2099-01-01T00:00:00Z", "type": "metrics",
         "values": {"loss": float("nan")}},
    )
    rc, out = _run(capfd, app_layout, action="list", extra_args=["--json"])
    assert rc == 0
    assert json.loads(out)[0]["metrics"].get("loss") is None


def test_list_json_on_an_empty_app(app_layout, capfd):
    _bootstrap(app_layout)
    rc, out = _run(capfd, app_layout, action="list", extra_args=["--json"])
    assert rc == 0
    assert json.loads(out) == []


SHOW_KEYS = LIST_KEYS | {"base_version", "base_commit", "log", "log_total", "patches"}


def test_show_json_is_machine_readable(app_layout, capfd):
    outer, inner, last = _three_runs(app_layout)
    rc, out = _run(capfd, app_layout, action="show", version="@1", extra_args=["--json"])
    assert rc == 0
    run = json.loads(out)
    assert SHOW_KEYS <= set(run), SHOW_KEYS - set(run)
    assert run["verstr"] == outer and run["idx"] == 1
    assert run["children"] == [inner] and run["kind"] == "outer"
    assert run["metrics"]["loss"] == 0.4
    assert run["log_total"] == len(run["log"]) == 2
    assert [e["type"] for e in run["log"]] == ["create", "metrics"]
