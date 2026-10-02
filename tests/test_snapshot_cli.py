"""`vmn snapshot` as a built-in vmn command: thin records, locking, --json, delete."""
import json
import os
from types import SimpleNamespace

import pytest
import yaml

from helpers import _bootstrap, _snapshot, extract_dev_verstr

from version_stamp.cli import entry, plugin_api, plugins

MB = 1024 * 1024


def _dirty(app_layout, filename="work.txt", content="dirty"):
    path = os.path.join(app_layout.repo_path, filename)
    if not os.path.exists(path):
        app_layout.write_file_commit_and_push("test_repo_0", filename, "initial")
    with open(path, "w") as f:
        f.write(content)


def _create(app_layout, capfd, **kwargs):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, **kwargs) == 0
    return extract_dev_verstr(capfd.readouterr().out)


def _vmn_dir(app_layout, *parts):
    return os.path.join(app_layout.repo_path, ".vmn", *parts)


def _record_dir(app_layout, verstr):
    return _vmn_dir(app_layout, "store", "snapshots", app_layout.app_name, verstr)


def _code_dir(app_layout):
    return _vmn_dir(app_layout, "store", "code", app_layout.app_name)


def _code_keys(app_layout):
    base = _code_dir(app_layout)
    return sorted(e for e in os.listdir(base) if not e.startswith(".")) if os.path.isdir(base) else []


def _record_meta(app_layout, verstr):
    with open(os.path.join(_record_dir(app_layout, verstr), "metadata.yml")) as f:
        return yaml.safe_load(f)


def test_create_writes_a_thin_record_and_one_code_object(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout)
    with open(os.path.join(app_layout.repo_path, "new.txt"), "w") as f:
        f.write("untracked")
    verstr = _create(app_layout, capfd)

    assert sorted(os.listdir(_record_dir(app_layout, verstr))) == ["metadata.yml"]
    meta = _record_meta(app_layout, verstr)
    assert _code_keys(app_layout) == [meta["code"]]
    assert meta["code"] == f"{meta['code_verstr']}.{meta['diff_hash']}"
    assert meta["has_working_tree_patch"] and meta["has_untracked_files"]


def test_recreating_the_same_state_keeps_verstr_and_number(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, content="state A")
    v_a = _create(app_layout, capfd)
    stamp_a = _record_meta(app_layout, v_a)["timestamp"]
    _dirty(app_layout, content="state B")
    _create(app_layout, capfd)
    _dirty(app_layout, content="state A")

    assert _create(app_layout, capfd, note="again") == v_a
    meta = _record_meta(app_layout, v_a)
    assert meta["timestamp"] == stamp_a
    assert meta["note"] == "again"
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list") == 0
    assert f"[1] {v_a}" in capfd.readouterr().out
    assert len(_code_keys(app_layout)) == 2


def test_create_warns_about_skipped_untracked_paths(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    _dirty(app_layout)
    with open(os.path.join(app_layout.repo_path, "weights.bin"), "wb") as f:
        f.write(b"x" * 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    captured = capfd.readouterr()
    assert "weights.bin" in captured.out + captured.err
    assert "VMN_SNAPSHOT_MAX_FILE_MB" in captured.out + captured.err


@pytest.mark.parametrize("action,locks", [
    ("list", False), ("show", False), ("diff", False), ("export", False),
    ("create", True), ("note", True), ("restore", True), ("delete", True),
])
def test_read_only_actions_take_no_lock(action, locks):
    assert entry._takes_repo_lock(SimpleNamespace(command="snapshot", action=action)) is locks


class _RecordingLock:
    acquired = 0

    def acquire(self):
        _RecordingLock.acquired += 1

    def release(self):
        pass


def test_list_runs_without_acquiring_the_repo_lock(app_layout, monkeypatch):
    _bootstrap(app_layout)
    _dirty(app_layout)
    monkeypatch.setattr(entry, "get_repo_lock", lambda root: _RecordingLock())
    _RecordingLock.acquired = 0
    assert _snapshot(app_layout.app_name, action="list") == 0
    assert _RecordingLock.acquired == 0
    assert _snapshot(app_layout.app_name) == 0
    assert _RecordingLock.acquired == 1


def test_store_flag_without_vmn_exp_is_an_error(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    _dirty(app_layout)
    monkeypatch.setattr(plugins, "_plugin_entry_points", lambda: [])
    monkeypatch.setattr(plugin_api, "_snapshot_store_opener", None)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, store="s3://bucket/prefix") == 1
    assert "pip install vmn-exp" in capfd.readouterr().err
    assert not os.path.isdir(_vmn_dir(app_layout, "store", "snapshots", app_layout.app_name))


def test_list_and_show_json(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout)
    verstr = _create(app_layout, capfd, note="n1", meta=["k=v"])

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list", as_json=True) == 0
    rows = json.loads(capfd.readouterr().out)
    assert [(r["index"], r["verstr"], r["note"]) for r in rows] == [(1, verstr, "n1")]
    assert rows[0]["user_meta"] == {"k": "v"}

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="show", as_json=True) == 0
    shown = json.loads(capfd.readouterr().out)
    assert shown["metadata"]["verstr"] == verstr
    assert "dirty" in shown["patches"]["working_tree"]


def _fake_run_referencing(app_layout, code):
    run_dir = _vmn_dir(app_layout, "store", "runs", app_layout.app_name, "0.0.1-dev.run0001.r1")
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "metadata.yml"), "w") as f:
        yaml.dump({"verstr": "0.0.1-dev.run0001.r1", "code": code}, f)


def test_delete_drops_unreferenced_code(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, content="kept by a run")
    kept = _create(app_layout, capfd)
    kept_code = _record_meta(app_layout, kept)["code"]
    _fake_run_referencing(app_layout, kept_code)
    _dirty(app_layout, content="nobody else")
    dropped = _create(app_layout, capfd)

    assert _snapshot(app_layout.app_name, action="delete", version=kept) == 0
    assert _snapshot(app_layout.app_name, action="delete", version=dropped) == 0

    assert not os.path.exists(_record_dir(app_layout, kept))
    assert not os.path.exists(_record_dir(app_layout, dropped))
    assert _code_keys(app_layout) == [kept_code]


def test_delete_requires_a_version(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout)
    _create(app_layout, capfd)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="delete") == 1
    assert "-v" in capfd.readouterr().err
