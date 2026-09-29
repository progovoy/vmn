"""`vmn snapshot restore/export/diff --store <uri>` read a store's snapshots,
and restore's safety snapshot lands in that store."""
import os
import subprocess

import pytest

from helpers import _bootstrap, _snapshot, extract_dev_verstr


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_PREFIX",
                "VMN_EXPERIMENT_ENDPOINT_URL", "VMN_EXPERIMENT_DIR", "VMN_EXP_OFFLINE"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def store(tmp_path):
    return f"file://{tmp_path / 'store'}"


def _work(app_layout):
    return os.path.join(app_layout.repo_path, "work.txt")


def _read(path):
    with open(path) as f:
        return f.read()


def _stored_snapshot(app_layout, capfd, store, content):
    if not os.path.exists(_work(app_layout)):
        app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "committed\n")
    with open(_work(app_layout), "w") as f:
        f.write(content)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, store=store) == 0
    return extract_dev_verstr(capfd.readouterr().out)


def _store_records(tmp_path, app_layout):
    base = tmp_path / "store" / ".vmn" / app_layout.app_name / "snapshots"
    return sorted(e.name for e in base.iterdir() if not e.name.startswith("."))


def test_restore_through_a_store_saves_the_replaced_work_there(app_layout, capfd, store, tmp_path):
    _bootstrap(app_layout)
    v_a = _stored_snapshot(app_layout, capfd, store, "state A\n")
    with open(_work(app_layout), "w") as f:
        f.write("state B\n")

    assert _snapshot(app_layout.app_name, action="restore", version=v_a, store=store) == 0

    assert _read(_work(app_layout)) == "state A\n"
    assert len(_store_records(tmp_path, app_layout)) == 2


def test_export_and_diff_through_a_store(app_layout, capfd, store, tmp_path):
    _bootstrap(app_layout)
    verstr = _stored_snapshot(app_layout, capfd, store, "STORED_SIDE\n")
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)
    out_dir = str(tmp_path / "exported")

    assert _snapshot(app_layout.app_name, action="export", version=verstr,
                     output=out_dir, store=store) == 0
    assert _read(os.path.join(out_dir, "work.txt")) == "STORED_SIDE\n"

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="diff", version=verstr, store=store) == 0
    assert "-STORED_SIDE" in capfd.readouterr().out
