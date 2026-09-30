"""Restoring a captured dev version: `vmn-exp restore`, `vmn goto -v <dev>`
and the safety net that saves dirty work a restore would clobber."""
import os
import shutil
import subprocess

from exp_helpers import (
    _bootstrap,
    _experiment,
    _goto,
    _storage,
    extract_dev_verstr,
)


def _write(app_layout, name, content):
    path = os.path.join(app_layout.repo_path, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def _read(path):
    with open(path) as f:
        return f.read()


def _checkout_clean(app_layout):
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, capture_output=True)


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _captured_state(app_layout, capfd, name, content):
    """Commit *name*, dirty it with *content* and record it. Returns (path, verstr)."""
    app_layout.write_file_commit_and_push("test_repo_0", name, "committed")
    path = _write(app_layout, name, content)
    return path, _create(app_layout, capfd)


def _safety_snapshots(app_layout):
    return _storage(app_layout, subdir="snapshots").list_snapshots(app_layout.app_name)


def test_goto_restores_a_recorded_dev_version(app_layout, capfd):
    _bootstrap(app_layout)
    path, verstr = _captured_state(app_layout, capfd, "goto_test.txt", "goto content")
    _checkout_clean(app_layout)
    assert _read(path) == "committed"

    assert _goto(app_layout.app_name, version=verstr) == 0
    assert _read(path) == "goto content"


def test_untracked_files_roundtrip_through_goto(app_layout, capfd):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial")
    tracked = _write(app_layout, "tracked.txt", "dirty tracked")
    script = _write(app_layout, "new_script.py", "print('hello')\n")
    config = _write(app_layout, os.path.join("data", "config.json"), '{"key": "value"}\n')
    verstr = _create(app_layout, capfd)

    os.remove(script)
    shutil.rmtree(os.path.dirname(config))
    _checkout_clean(app_layout)
    assert _read(tracked) == "initial"

    assert _goto(app_layout.app_name, version=verstr) == 0
    assert _read(script) == "print('hello')\n"
    assert _read(config) == '{"key": "value"}\n'
    assert _read(tracked) == "dirty tracked"


def test_restore_over_dirty_work_saves_it_for_goto(app_layout, capfd):
    """The safety net names a `vmn goto` that brings the clobbered work back."""
    _bootstrap(app_layout)
    path, v_a = _captured_state(app_layout, capfd, "safety.txt", "state A")
    _write(app_layout, "safety.txt", "state B unsaved")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="restore", version=v_a) == 0
    out = capfd.readouterr()
    assert _read(path) == "state A"

    saved = _safety_snapshots(app_layout)
    assert len(saved) == 1
    saved_verstr = saved[0]["verstr"]
    assert "auto-saved before restore" in saved[0]["note"]
    hint = f"vmn goto -v {saved_verstr} {app_layout.app_name}"
    assert hint in out.out + out.err
    assert "vmn snapshot" not in out.out + out.err

    assert _goto(app_layout.app_name, version=saved_verstr) == 0
    assert _read(path) == "state B unsaved"


def test_restore_of_the_current_state_saves_nothing(app_layout, capfd):
    _bootstrap(app_layout)
    _, verstr = _captured_state(app_layout, capfd, "same.txt", "state A")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="restore", version=verstr) == 0
    out = capfd.readouterr()
    assert "Current work saved as" not in out.out + out.err
    assert _safety_snapshots(app_layout) == []


def test_goto_dev_version_over_dirty_work_saves_it(app_layout, capfd):
    _bootstrap(app_layout)
    path, v_a = _captured_state(app_layout, capfd, "goto_safety.txt", "state A")
    _write(app_layout, "goto_safety.txt", "state B unsaved")

    capfd.readouterr()
    assert _goto(app_layout.app_name, version=v_a) == 0
    out = capfd.readouterr()
    assert "Current work saved as" in out.out + out.err
    assert _read(path) == "state A"
    assert len(_safety_snapshots(app_layout)) == 1


def test_goto_dev_version_from_a_clean_tree_is_silent_and_saves_nothing(app_layout, capfd):
    _bootstrap(app_layout)
    path, verstr = _captured_state(app_layout, capfd, "clean.txt", "state A")
    _checkout_clean(app_layout)

    capfd.readouterr()
    assert _goto(app_layout.app_name, version=verstr) == 0
    out = capfd.readouterr()
    assert "No local changes to snapshot" not in out.out + out.err
    assert _read(path) == "state A"
    assert _safety_snapshots(app_layout) == []
