"""Plan 25 F1: `vmn-exp show -v` and `get_run` of an indexed app are point
reads — with 2k runs they build no snapshot of the app and print what the
snapshot path printed."""
import json
import os

import pytest
import yaml
from exp_helpers import _exp, _storage
from vmn_exp.core import index as experiment_index
from vmn_exp.core import index_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache
from vmn_exp.sdk.reader import get_run

RUNS = 2000
OUTER, INNER = "0.0.1-dev.aaaa0001", "0.0.1-dev.aaaa0002"


def _verstr(i):
    return f"0.0.1-dev.r{i:05d}"


def _write(app_layout, verstr, i, parent=None):
    path = os.path.join(app_layout.repo_path, ".vmn", "store", "runs",
                        app_layout.app_name, verstr)
    os.makedirs(path)
    meta = {"format_version": 1, "verstr": verstr, "code_verstr": verstr,
            "note": f"n-{verstr}", "timestamp": f"2026-09-21T{i // 3600:02d}:"
            f"{i // 60 % 60:02d}:{i % 60:02d}Z"}
    if parent:
        meta["parent"] = parent
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    with open(os.path.join(path, "run_state.yml"), "w") as f:
        f.write("state: finished\nexit_code: 0\n")


@pytest.fixture
def many(app_layout):
    for i in range(RUNS):
        _write(app_layout, _verstr(i), i + 10)
    _write(app_layout, OUTER, 1)
    _write(app_layout, INNER, 2, parent=OUTER)
    return app_layout


def _no_snapshots(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("built a snapshot of the app")

    monkeypatch.setattr(RowCache, "snapshot", refuse)
    monkeypatch.setattr(IndexSnapshot, "build", refuse)
    monkeypatch.setattr(ExperimentIndex, "refresh", refuse)
    monkeypatch.setattr(ExperimentIndex, "_refresh_locked", refuse)
    monkeypatch.setattr(index_store, "decode_records", refuse)
    monkeypatch.setattr(experiment_index, "_SHARED", {})  # a fresh process


def _show(capfd, app_layout, version, *extra):
    capfd.readouterr()
    rc = _exp(app_layout.app_name, action="show", version=version, extra_args=list(extra))
    out = capfd.readouterr().out
    assert rc == 0, out
    return out


def _timeless(out):
    """*out* without what moves with the clock (``stale_sec``)."""
    if not out.startswith("{"):
        return out
    shown = json.loads(out)
    shown.pop("stale_sec", None)
    return shown


@pytest.mark.parametrize("ref,extra", [(OUTER, ()), (OUTER, ("--json",)),
                                       ("@1", ()), (_verstr(7), ("--json",))])
def test_show_is_a_point_read(many, capfd, monkeypatch, ref, extra):
    before = _show(capfd, many, ref, *extra)  # builds and persists the index
    _no_snapshots(monkeypatch)
    assert _timeless(_show(capfd, many, ref, *extra)) == _timeless(before)
    if ref == OUTER:
        assert f"Children:  {INNER}" in before or json.loads(before)["children"] == [INNER]


def test_show_sees_a_child_created_since_the_last_index_refresh(many, capfd, monkeypatch):
    _show(capfd, many, OUTER)
    late = "0.0.9-dev.late0001"
    _write(many, late, RUNS + 100, parent=OUTER)
    _no_snapshots(monkeypatch)
    shown = json.loads(_show(capfd, many, OUTER, "--json"))
    assert shown["children"] == [INNER, late]
    assert json.loads(_show(capfd, many, "latest", "--json"))["verstr"] == late


def test_get_run_is_a_point_read(many, monkeypatch):
    storage = _storage(many)
    before = get_run(many.app_name, OUTER, storage=storage)
    _no_snapshots(monkeypatch)
    after = get_run(many.app_name, OUTER, storage=storage)
    for key in ("heartbeat", "duration_sec", "stale_sec"):
        before.pop(key, None), after.pop(key, None)
    assert after == before
    assert after["children"] == [INNER] and after["idx"] == 1


def test_a_point_read_signs_no_record_directory(many, capfd, monkeypatch):
    """Telling new and gone records apart needs their names only: a point
    read never signs every record directory (a stat each, its cost at 100k)."""
    from vmn_exp.storage.local import LocalSnapshotStorage

    _show(capfd, many, OUTER)

    def refuse(*a, **kw):
        raise AssertionError("signed every record directory")

    monkeypatch.setattr(LocalSnapshotStorage, "list_record_names", refuse)
    _no_snapshots(monkeypatch)
    late = "0.0.9-dev.late0002"
    _write(many, late, RUNS + 100, parent=OUTER)
    shown = json.loads(_show(capfd, many, OUTER, "--json"))
    assert shown["children"] == [INNER, late]
    _write_gone = os.path.join(many.repo_path, ".vmn", "store", "runs", many.app_name, late)
    import shutil

    shutil.rmtree(_write_gone)
    assert json.loads(_show(capfd, many, OUTER, "--json"))["children"] == [INNER]
