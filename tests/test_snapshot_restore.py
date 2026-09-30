"""`vmn snapshot restore`: reapply a snapshot, auto-saving the work it replaces."""
import os
import shutil
import subprocess

import pytest
import yaml

from helpers import _bootstrap, _snapshot, extract_dev_verstr

MB = 1024 * 1024


def _path(app_layout, name):
    return os.path.join(app_layout.repo_path, name)


def _read(app_layout, name):
    with open(_path(app_layout, name)) as f:
        return f.read()


def _write(app_layout, name, content):
    with open(_path(app_layout, name), "w") as f:
        f.write(content)


def _snapshot_of(app_layout, capfd, content, name="work.txt"):
    """Commit *name*, dirty it with *content* and snapshot it; the verstr."""
    if not os.path.exists(_path(app_layout, name)):
        app_layout.write_file_commit_and_push("test_repo_0", name, "committed")
    _write(app_layout, name, content)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _discard_changes(app_layout):
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)
    subprocess.run(["git", "clean", "-fdq"], cwd=app_layout.repo_path, check=True)


def _restore(app_layout, capfd, **kwargs):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="restore", **kwargs)
    captured = capfd.readouterr()
    return ret, captured.out + captured.err


def _records(app_layout):
    base = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "snapshots")
    found = {}
    for name in os.listdir(base):
        meta_path = os.path.join(base, name, "metadata.yml")
        if os.path.isfile(meta_path):
            with open(meta_path) as f:
                found[name] = yaml.safe_load(f)
    return found


@pytest.fixture
def stamped(app_layout):
    _bootstrap(app_layout)
    return app_layout


def test_restore_reapplies_tracked_and_untracked_changes(stamped, capfd):
    _write(stamped, "new_script.py", "print('hi')\n")
    verstr = _snapshot_of(stamped, capfd, "snapshot state")
    _discard_changes(stamped)

    ret, _ = _restore(stamped, capfd, version=verstr)

    assert ret == 0
    assert _read(stamped, "work.txt") == "snapshot state"
    assert _read(stamped, "new_script.py") == "print('hi')\n"


def test_restore_latest(stamped, capfd):
    _snapshot_of(stamped, capfd, "first")
    _snapshot_of(stamped, capfd, "second")
    _discard_changes(stamped)

    ret, _ = _restore(stamped, capfd, latest=True)

    assert ret == 0
    assert _read(stamped, "work.txt") == "second"


def test_restore_needs_a_ref(stamped, capfd):
    _snapshot_of(stamped, capfd, "state")
    ret, out = _restore(stamped, capfd)
    assert ret == 1
    assert "-v" in out


def test_restore_of_an_unknown_snapshot_fails(stamped, capfd):
    _snapshot_of(stamped, capfd, "state")
    ret, out = _restore(stamped, capfd, version="0.0.1-dev.0000000.0000000")
    assert ret == 1
    assert "not found" in out


def test_restore_over_dirty_work_saves_it_first(stamped, capfd):
    v_a = _snapshot_of(stamped, capfd, "state A")
    _write(stamped, "work.txt", "state B unsaved")

    ret, out = _restore(stamped, capfd, version=v_a)

    assert ret == 0
    assert _read(stamped, "work.txt") == "state A"
    saved = [v for v, meta in _records(stamped).items() if v != v_a]
    assert len(saved) == 1
    assert _records(stamped)[saved[0]]["note"] == "auto-saved before restore"
    assert f"vmn snapshot restore {stamped.app_name} -v {saved[0]}" in out

    ret, _ = _restore(stamped, capfd, version=saved[0])
    assert ret == 0
    assert _read(stamped, "work.txt") == "state B unsaved"


def test_restore_of_the_current_state_saves_nothing(stamped, capfd):
    verstr = _snapshot_of(stamped, capfd, "state A")

    ret, out = _restore(stamped, capfd, version=verstr)

    assert ret == 0
    assert list(_records(stamped)) == [verstr]
    assert "vmn snapshot restore" not in out


def test_safety_save_keeps_an_existing_records_note(stamped, capfd):
    v_a = _snapshot_of(stamped, capfd, "state A")
    capfd.readouterr()
    v_b = _snapshot_of(stamped, capfd, "state B")
    assert _snapshot(stamped.app_name, action="note", version=v_b, note="mine") == 0

    ret, _ = _restore(stamped, capfd, version=v_a)

    assert ret == 0
    assert _records(stamped)[v_b]["note"] == "mine"


def test_restore_refuses_when_the_safety_save_would_drop_untracked_files(
    stamped, capfd, monkeypatch
):
    v_a = _snapshot_of(stamped, capfd, "state A")
    _write(stamped, "work.txt", "state B unsaved")
    with open(_path(stamped, "weights.bin"), "wb") as f:
        f.write(b"x" * 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    ret, out = _restore(stamped, capfd, version=v_a)

    assert ret == 1
    assert "weights.bin" in out and "--force" in out
    assert _read(stamped, "work.txt") == "state B unsaved"
    assert os.path.isfile(_path(stamped, "weights.bin"))
    assert list(_records(stamped)) == [v_a]


def test_restore_force_proceeds_despite_dropped_untracked_files(
    stamped, capfd, monkeypatch
):
    v_a = _snapshot_of(stamped, capfd, "state A")
    _write(stamped, "work.txt", "state B unsaved")
    with open(_path(stamped, "weights.bin"), "wb") as f:
        f.write(b"x" * 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    ret, _ = _restore(stamped, capfd, version=v_a, force=True)

    assert ret == 0
    assert _read(stamped, "work.txt") == "state A"
    saved = [meta for v, meta in _records(stamped).items() if v != v_a]
    assert saved[0]["untracked_skipped"] == ["weights.bin"]


def test_restore_refuses_a_snapshot_whose_code_is_gone(stamped, capfd):
    verstr = _snapshot_of(stamped, capfd, "state A")
    _write(stamped, "work.txt", "state B unsaved")
    shutil.rmtree(os.path.join(stamped.repo_path, ".vmn", "vmn-code"))

    ret, out = _restore(stamped, capfd, version=verstr)

    assert ret == 1
    assert "code" in out
    assert _read(stamped, "work.txt") == "state B unsaved"
