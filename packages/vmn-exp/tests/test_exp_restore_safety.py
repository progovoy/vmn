"""`vmn-exp restore` and `vmn goto -v <dev>` restore through `vmn snapshot`'s
restore: the work they replace is saved as a thin snapshot record (its code in
the shared code store), and untracked files over the snapshot size caps that
the reset would delete make them refuse unless --force."""
import os

import yaml

from exp_helpers import _bootstrap, _experiment, _storage, extract_dev_verstr
from version_stamp.cli import vmn_run
from version_stamp.core.logging import reset_logger

MB = 1024 * 1024


def _path(app_layout, name):
    return os.path.join(app_layout.repo_path, name)


def _write(app_layout, name, content):
    with open(_path(app_layout, name), "w") as f:
        f.write(content)


def _read(app_layout, name):
    with open(_path(app_layout, name)) as f:
        return f.read()


def _recorded(app_layout, capfd, content):
    """Dirty work.txt with *content* and record it as a run; the verstr."""
    _write(app_layout, "work.txt", content)
    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr
    return verstr


def _snapshot_dir(app_layout):
    return os.path.join(app_layout.repo_path, ".vmn", "store", "snapshots", app_layout.app_name)


def _safety_verstrs(app_layout):
    return [m["verstr"] for m in _storage(app_layout, area="snapshots")
            .list_snapshots(app_layout.app_name)]


def _goto(app_layout, verstr, *flags):
    reset_logger()
    return vmn_run(["goto", "-v", verstr, *flags, app_layout.app_name])[0]


def _restore(app_layout, verstr, *flags):
    return _experiment(app_layout.app_name, action="restore", version=verstr,
                       extra_args=list(flags))


def _stage(app_layout, capfd, oversized=False, monkeypatch=None):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "committed")
    target = _recorded(app_layout, capfd, "state A")
    _write(app_layout, "work.txt", "state B unsaved")
    if oversized:
        with open(_path(app_layout, "weights.bin"), "wb") as f:
            f.write(b"x" * 2 * MB)
        monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")
    return target


def test_restore_saves_the_replaced_work_as_a_thin_record(app_layout, capfd):
    target = _stage(app_layout, capfd)

    assert _restore(app_layout, target) == 0

    assert _read(app_layout, "work.txt") == "state A"
    [saved] = _safety_verstrs(app_layout)
    record_dir = os.path.join(_snapshot_dir(app_layout), saved)
    assert os.listdir(record_dir) == ["metadata.yml"]
    with open(os.path.join(record_dir, "metadata.yml")) as f:
        assert yaml.safe_load(f)["code"]
    assert _goto(app_layout, saved) == 0
    assert _read(app_layout, "work.txt") == "state B unsaved"


def test_restore_refuses_to_delete_untracked_files_over_the_caps(
    app_layout, capfd, monkeypatch
):
    target = _stage(app_layout, capfd, oversized=True, monkeypatch=monkeypatch)
    capfd.readouterr()

    assert _restore(app_layout, target) == 1

    out = capfd.readouterr()
    assert "weights.bin" in out.out + out.err and "--force" in out.out + out.err
    assert _read(app_layout, "work.txt") == "state B unsaved"
    assert os.path.isfile(_path(app_layout, "weights.bin"))
    assert _safety_verstrs(app_layout) == []


def test_restore_force_loses_them_and_restores(app_layout, capfd, monkeypatch):
    target = _stage(app_layout, capfd, oversized=True, monkeypatch=monkeypatch)

    assert _restore(app_layout, target, "--force") == 0

    assert _read(app_layout, "work.txt") == "state A"
    assert len(_safety_verstrs(app_layout)) == 1


def test_goto_of_a_dev_version_refuses_the_same_way(app_layout, capfd, monkeypatch):
    target = _stage(app_layout, capfd, oversized=True, monkeypatch=monkeypatch)

    assert _goto(app_layout, target) == 1
    assert _read(app_layout, "work.txt") == "state B unsaved"

    assert _goto(app_layout, target, "--force") == 0
    assert _read(app_layout, "work.txt") == "state A"


def test_restore_refuses_legacy_in_record_patches(app_layout, capfd, caplog):
    _bootstrap(app_layout)
    target = _recorded(app_layout, capfd, "state A")
    storage, app = _storage(app_layout), app_layout.app_name
    source, patches = storage.load(app, target)
    storage.save(app, target, {k: v for k, v in source.items() if k != "code"}, patches)
    _write(app_layout, "work.txt", "state B unsaved")

    assert _restore(app_layout, target) == 1
    assert "vmn-exp migrate" in caplog.text + capfd.readouterr().err
    assert _read(app_layout, "work.txt") == "state B unsaved"
