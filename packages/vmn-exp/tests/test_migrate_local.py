"""``vmn-exp migrate`` on local stores: the repo-local store, ``--dir`` and
``file://`` (docs/plans/14-store-layout.md §4)."""
import json
import os

import pytest
import yaml

from migrate_fixtures import (
    APP, LocalRaw, expected_v2_keys, local_key, log_paths, v1_records, write_v1,
)
from vmn_exp.cli import migrate as migrate_mod
from vmn_exp.cli.migrate import run_migrate
from vmn_exp.storage.store_marker import StoreLayoutError, forget_checked


@pytest.fixture(autouse=True)
def _fresh_marker_cache():
    forget_checked()
    yield
    forget_checked()


def _v1_dir(tmp_path, live=False):
    raw = LocalRaw(tmp_path)
    write_v1(raw.put, local_key, v1_records(live))
    raw.put(f".vmn/{APP}/conf.yml", b"conf: {}\n")
    raw.put(f".vmn/{APP}/experiments/.gitignore", b"*\n")
    raw.put(f".vmn/{APP}/experiments/.index.sqlite", b"cache")
    return raw


def _marker(path):
    with open(os.path.join(path, "store.yml")) as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("form", ["dir", "file_uri"])
def test_migrates_a_v1_dir_store_to_layout_2(tmp_path, form):
    raw = _v1_dir(tmp_path)
    args = ["--dir", str(tmp_path)] if form == "dir" else ["--store", f"file://{tmp_path}"]
    assert run_migrate(args) == 0
    v2 = raw.keys() - {f".vmn/{APP}/conf.yml"}
    assert v2 == expected_v2_keys(v1_records()) | {"store.yml"}
    assert _marker(tmp_path)["layout"] == 2
    assert "migrating" not in _marker(tmp_path)


def test_repo_local_store_moves_under_dot_vmn_store(tmp_path, monkeypatch):
    _v1_dir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))
    assert run_migrate([]) == 0
    store = tmp_path / ".vmn" / "store"
    assert LocalRaw(store).keys() == (
        expected_v2_keys(v1_records()) | {"store.yml", ".gitignore"})
    assert not (tmp_path / ".vmn" / "my" / "app" / "experiments").exists()
    assert (tmp_path / ".vmn" / "my" / "app" / "conf.yml").exists()


def test_record_contents_are_converted(tmp_path):
    raw = _v1_dir(tmp_path)
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    rec = "runs/my-app/r1"
    assert log_paths(raw, f"{rec}/log/w1.jsonl") == [None, "outputs/media/img/1.png"]
    assert log_paths(raw, f"{rec}/log/w1@000001.jsonl") == ["outputs/tables/t/2.json"]
    assert json.loads(raw.get(f"{rec}/log/v1.jsonl")) == {"type": "note", "text": "old"}
    assert raw.get(f"{rec}/outputs/media/img/1.png") == b"PNG"
    assert raw.get(f"{rec}/artifacts/model.bin") == b"weights"


def test_migrate_is_idempotent(tmp_path):
    raw = _v1_dir(tmp_path)
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    before = {k: raw.get(k) for k in raw.keys()}
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    assert {k: raw.get(k) for k in raw.keys()} == before


def test_dry_run_changes_nothing(tmp_path, capsys):
    raw = _v1_dir(tmp_path)
    before = {k: raw.get(k) for k in raw.keys()}
    assert run_migrate(["--dir", str(tmp_path), "--dry-run"]) == 0
    assert {k: raw.get(k) for k in raw.keys()} == before
    assert "runs/my-app/r1" in capsys.readouterr().out


def test_live_runs_stop_the_migration_with_a_list(tmp_path, capsys):
    raw = _v1_dir(tmp_path, live=True)
    before = {k: raw.get(k) for k in raw.keys()}
    assert run_migrate(["--dir", str(tmp_path)]) == 1
    assert "r2" in capsys.readouterr().err
    assert {k: raw.get(k) for k in raw.keys()} == before


def test_skip_live_leaves_live_runs_for_a_later_rerun(tmp_path):
    raw = _v1_dir(tmp_path, live=True)
    assert run_migrate(["--dir", str(tmp_path), "--skip-live"]) == 0
    assert f"{local_key(('run',), 'r2')}/metadata.yml" in raw.keys()
    assert "runs/my-app/r2/metadata.yml" not in raw.keys()
    assert "runs/my-app/r1/metadata.yml" in raw.keys()


def _kill_after(monkeypatch, n):
    real, calls = migrate_mod.migrate_record, []

    def dying(*args, **kwargs):
        if len(calls) == n:
            raise KeyboardInterrupt
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(migrate_mod, "migrate_record", dying)


def test_writers_refuse_while_migrating(tmp_path, monkeypatch):
    from vmn_exp.storage.open import open_storage

    _v1_dir(tmp_path)
    _kill_after(monkeypatch, 2)
    with pytest.raises(KeyboardInterrupt):
        run_migrate(["--dir", str(tmp_path)])
    assert _marker(tmp_path)["migrating"] is True
    forget_checked()
    with pytest.raises(StoreLayoutError, match="migrating"):
        open_storage(None, str(tmp_path), area="runs")


def test_resumes_after_a_kill(tmp_path, monkeypatch):
    raw = _v1_dir(tmp_path)
    _kill_after(monkeypatch, 3)
    with pytest.raises(KeyboardInterrupt):
        run_migrate(["--dir", str(tmp_path)])
    monkeypatch.undo()
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    v2 = raw.keys() - {f".vmn/{APP}/conf.yml"}
    assert v2 == expected_v2_keys(v1_records()) | {"store.yml"}
    assert "migrating" not in _marker(tmp_path)


def test_rerun_deletes_the_old_copy_of_a_done_record(tmp_path):
    raw = _v1_dir(tmp_path)
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    old = local_key(("snap",), "s1")
    raw.put(f"{old}/metadata.yml", b"verstr: s1\n")
    assert run_migrate(["--dir", str(tmp_path)]) == 0
    assert not any(k.startswith(old) for k in raw.keys())
