"""Local snapshot stores use the v2 layout under ``.vmn/store/``."""
import os

import pytest

from version_stamp.snapshot.stores import local_snapshot_stores


@pytest.mark.parametrize("app,key", [("app", "app"), ("root/svc", "root-svc")])
def test_records_and_code_use_store_layout(tmp_path, app, key):
    stores = local_snapshot_stores(str(tmp_path))
    stores.records.save(app, "0.0.1-dev.abc", {"verstr": "0.0.1-dev.abc"}, {})
    stores.code.save(app, "0.0.1-dev.abc.ff", {"verstr": "k"}, {})
    store = tmp_path / ".vmn" / "store"
    assert (store / "snapshots" / key / "0.0.1-dev.abc" / "metadata.yml").is_file()
    assert (store / "code" / key / "0.0.1-dev.abc.ff" / "metadata.yml").is_file()
    assert (store / ".gitignore").read_text() == "*\n"
    assert not os.path.exists(store / "snapshots" / key / ".gitignore")
    assert stores.records.load(app, "0.0.1-dev.abc")[0]["verstr"] == "0.0.1-dev.abc"


def test_runs_are_scanned_from_runs_dir(tmp_path):
    stores = local_snapshot_stores(str(tmp_path))
    stores.runs.save("root/svc", "0.0.1-dev.run", {"verstr": "r", "code": "k"}, {})
    assert (tmp_path / ".vmn/store/runs/root-svc/0.0.1-dev.run").is_dir()


def _put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _v1_snapshot(tmp_path, app="my/app", verstr="0.0.1-dev.abc"):
    vmn = tmp_path / ".vmn"
    seg = app.replace("/", "~")
    _put(vmn / app / "snapshots" / verstr / "metadata.yml",
         f"verstr: {verstr}\ncode: {verstr}.ff\ntimestamp: '1'\n")
    _put(vmn / app / "snapshots" / ".gitignore", "*\n")
    code = vmn / "vmn-code" / seg / "experiments" / f"{verstr}.ff"
    _put(code / "metadata.yml", f"verstr: {verstr}.ff\n")
    _put(code / "working_tree.patch", "diff --git a/x b/x\n")
    _put(vmn / app / "conf.yml", "conf: {}\n")
    return vmn


@pytest.mark.parametrize("app,key", [("app", "app"), ("my/app", "my-app")])
def test_v1_local_snapshots_move_on_first_use(tmp_path, app, key):
    vmn = _v1_snapshot(tmp_path, app)
    stores = local_snapshot_stores(str(tmp_path))
    assert stores.records.list_verstrs(app) == ["0.0.1-dev.abc"]
    metadata, patches = stores.records.load(app, "0.0.1-dev.abc")
    assert patches["working_tree"] == "diff --git a/x b/x\n"
    assert "code_missing" not in metadata
    store = vmn / "store"
    moved = (store / "snapshots" / key / "0.0.1-dev.abc" / "metadata.yml").read_text()
    assert "format_version: 1" in moved
    assert "format_version: 1" in (
        store / "code" / key / "0.0.1-dev.abc.ff" / "metadata.yml").read_text()
    assert not (vmn / app / "snapshots").exists()
    assert not (vmn / "vmn-code").exists()
    assert (vmn / app / "conf.yml").is_file()


def test_v1_local_snapshot_never_overwrites_a_v2_record(tmp_path):
    _v1_snapshot(tmp_path)
    store = tmp_path / ".vmn" / "store" / "snapshots" / "my-app" / "0.0.1-dev.abc"
    _put(store / "metadata.yml", "format_version: 1\nverstr: 0.0.1-dev.abc\nnote: v2\n")
    stores = local_snapshot_stores(str(tmp_path))
    assert stores.records.load_metadata("my/app", "0.0.1-dev.abc")["note"] == "v2"
