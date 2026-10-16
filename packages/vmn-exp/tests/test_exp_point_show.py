"""Plan 25 F1: `vmn-exp show -v` and `get_run` of an indexed app are point
reads — with 2k runs they build no snapshot of the app and print what the
snapshot path printed."""
import json
import os
import shutil

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
    os.makedirs(path, exist_ok=True)
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


def _record_dir(app_layout, verstr):
    return os.path.join(app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr)


def _settle(app_layout):
    """Date the app's directory back: no later change shares its mtime."""
    path = os.path.dirname(_record_dir(app_layout, OUTER))
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns - 10**10))


def _refusing(monkeypatch, name):
    from vmn_exp.storage.local import LocalSnapshotStorage

    def refuse(*a, **kw):
        raise AssertionError(f"called {name}")

    monkeypatch.setattr(LocalSnapshotStorage, name, refuse)


def test_a_point_read_signs_no_record_directory(many, capfd, monkeypatch):
    """Telling new and gone records apart needs their names only: a point
    read never signs every record directory (a stat each, its cost at 100k)."""
    _show(capfd, many, OUTER)
    _refusing(monkeypatch, "list_record_names")
    _no_snapshots(monkeypatch)
    late = "0.0.9-dev.late0002"
    _write(many, late, RUNS + 100, parent=OUTER)
    shown = json.loads(_show(capfd, many, OUTER, "--json"))
    assert shown["children"] == [INNER, late]
    shutil.rmtree(_record_dir(many, late))
    assert json.loads(_show(capfd, many, OUTER, "--json"))["children"] == [INNER]


def test_a_point_read_of_an_unchanged_store_lists_no_record_name(many, capfd, monkeypatch):
    """No record came or went since the last point read (the app directory
    kept its settled mtime): nothing is listed at all."""
    _settle(many)
    _show(capfd, many, OUTER, "--json")  # builds the index
    before = _show(capfd, many, OUTER, "--json")  # a point read
    _refusing(monkeypatch, "list_record_keys")
    _no_snapshots(monkeypatch)
    assert _timeless(_show(capfd, many, OUTER, "--json")) == _timeless(before)


def test_a_claim_whose_metadata_lands_later_is_still_found(many, capfd, monkeypatch):
    """Writing a claimed record's metadata leaves the app directory's mtime
    alone: a point read that saw the claim does not vouch for the names."""
    claim = "0.0.9-dev.claim001"
    os.makedirs(_record_dir(many, claim))
    _settle(many)
    _show(capfd, many, OUTER)  # builds the index
    _show(capfd, many, OUTER)  # a point read: the claim is no run yet
    _write(many, claim, RUNS + 200)  # its metadata, inside its directory
    _no_snapshots(monkeypatch)
    assert json.loads(_show(capfd, many, "latest", "--json"))["verstr"] == claim
