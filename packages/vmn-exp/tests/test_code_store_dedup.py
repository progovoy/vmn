"""A run's code (patches + untracked tarball) is stored once per code identity.

Runs of the same code reference one code object in a reserved pseudo-app of
the same store instead of each carrying a copy; a second run of unchanged code
neither builds the untracked tarball nor uploads anything but its own record.
"""
import os
import shutil
import subprocess

import pytest
from exp_helpers import _bootstrap, _experiment, _goto, _storage, extract_dev_verstr

import version_stamp.devversion.untracked as dv_untracked
from vmn_exp.core.code_store import code_app
from vmn_exp.sdk import start_run
from vmn_exp.storage.files import METADATA_FILE, PATCH_FILES

PATCH_NAMES = [filename for _, filename, _ in PATCH_FILES]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def tarballs(monkeypatch):
    calls = []
    real = dv_untracked._collect_untracked_tarball

    def spy(repo_path):
        calls.append(repo_path)
        return real(repo_path)

    monkeypatch.setattr(dv_untracked, "_collect_untracked_tarball", spy)
    return calls


def _write(app_layout, name, content):
    path = os.path.join(app_layout.repo_path, name)
    with open(path, "w") as f:
        f.write(content)
    return path


def _read(path):
    with open(path) as f:
        return f.read()


def _dirty(app_layout, tracked="dirty", untracked="new file"):
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "committed")
    _write(app_layout, "tracked.txt", tracked)
    _write(app_layout, "untracked.txt", untracked)


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _clean_tree(app_layout):
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)
    os.remove(os.path.join(app_layout.repo_path, "untracked.txt"))


def _code_keys(app_layout):
    return _storage(app_layout).list_verstrs(code_app(app_layout.app_name))


def _run_dir(app_layout, verstr):
    return os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )


def _code_dir(app_layout, key):
    store = _storage(app_layout)._local
    return store._snapshot_dir(code_app(app_layout.app_name), key)


def test_identical_code_runs_share_one_code_object(app_layout, capfd, tarballs):
    _bootstrap(app_layout)
    _dirty(app_layout)

    first, second = _create(app_layout, capfd), _create(app_layout, capfd)

    assert first != second
    assert len(tarballs) == 1  # the second run found the code already stored
    keys = _code_keys(app_layout)
    assert len(keys) == 1
    for verstr in (first, second):
        meta = _storage(app_layout).load_metadata(app_layout.app_name, verstr)
        assert meta["code"] == keys[0]
        assert meta["has_untracked_files"] is True
        assert meta["has_working_tree_patch"] is True
        assert not set(PATCH_NAMES) & set(os.listdir(_run_dir(app_layout, verstr)))


def test_sdk_trials_of_one_tree_upload_the_payload_once(app_layout, tarballs, monkeypatch):
    from vmn_exp.storage.local import LocalSnapshotStorage

    saves = []
    real_save = LocalSnapshotStorage.save

    def spy(self, app_name, verstr, metadata, patches):
        saves.append(app_name)
        return real_save(self, app_name, verstr, metadata, patches)

    monkeypatch.setattr(LocalSnapshotStorage, "save", spy)
    _bootstrap(app_layout)
    _dirty(app_layout)

    ids = []
    for _ in range(3):
        with start_run(app_layout.app_name) as run:
            ids.append(run.id)

    assert len(set(ids)) == 3
    assert len(tarballs) == 1
    assert saves.count(code_app(app_layout.app_name)) == 1
    for verstr in ids:
        _, patches = _storage(app_layout).load(app_layout.app_name, verstr)
        assert patches["untracked_files"] and patches["working_tree"]


def test_every_run_of_shared_code_restores_the_exact_tree(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, tracked="shared dirty", untracked="shared new")
    first, second = _create(app_layout, capfd), _create(app_layout, capfd)
    tracked = os.path.join(app_layout.repo_path, "tracked.txt")
    untracked = os.path.join(app_layout.repo_path, "untracked.txt")

    for restore in (
        lambda: _experiment(app_layout.app_name, action="restore", version=first),
        lambda: _goto(app_layout.app_name, version=second),
    ):
        _clean_tree(app_layout)
        assert restore() == 0
        assert _read(tracked) == "shared dirty"
        assert _read(untracked) == "shared new"


def test_different_code_gets_its_own_code_object(app_layout, capfd, tarballs):
    _bootstrap(app_layout)
    _dirty(app_layout, untracked="one")
    first = _create(app_layout, capfd)
    _write(app_layout, "untracked.txt", "two")
    second = _create(app_layout, capfd)

    assert len(tarballs) == 2
    assert len(_code_keys(app_layout)) == 2
    load = _storage(app_layout).load_metadata
    assert load(app_layout.app_name, first)["code"] != load(app_layout.app_name, second)["code"]


def test_a_clean_tree_run_stores_no_code_object(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)

    assert _code_keys(app_layout) == []
    meta, patches = _storage(app_layout).load(app_layout.app_name, verstr)
    assert "code" not in meta
    assert not any(patches.values())
    assert _experiment(app_layout.app_name, action="restore", version=verstr) == 0


def test_an_incomplete_code_object_is_rewritten_by_the_next_run(app_layout, capfd, tarballs):
    _bootstrap(app_layout)
    _dirty(app_layout, tracked="dirty again", untracked="fresh")
    first = _create(app_layout, capfd)
    (key,) = _code_keys(app_layout)
    os.remove(os.path.join(_code_dir(app_layout, key), METADATA_FILE))

    second = _create(app_layout, capfd)

    assert len(tarballs) == 2
    assert _code_keys(app_layout) == [key]
    _clean_tree(app_layout)
    assert _experiment(app_layout.app_name, action="restore", version=first) == 0
    assert _read(os.path.join(app_layout.repo_path, "untracked.txt")) == "fresh"
    assert second != first


@pytest.mark.parametrize("damage", ["missing", "incomplete"])
@pytest.mark.parametrize("command", ["restore", "goto"])
def test_restore_refuses_when_the_code_object_is_unusable(
    app_layout, capfd, damage, command
):
    _bootstrap(app_layout)
    _dirty(app_layout, tracked="recorded", untracked="recorded new")
    verstr = _create(app_layout, capfd)
    (key,) = _code_keys(app_layout)
    code_dir = _code_dir(app_layout, key)
    if damage == "missing":
        shutil.rmtree(code_dir)
    else:
        os.remove(os.path.join(code_dir, METADATA_FILE))
    tracked = _write(app_layout, "tracked.txt", "unsaved work")

    capfd.readouterr()
    if command == "restore":
        err = _experiment(app_layout.app_name, action="restore", version=verstr)
    else:
        err = _goto(app_layout.app_name, version=verstr)
    out = capfd.readouterr()

    assert err == 1
    assert f"code snapshot {key} is missing" in out.out + out.err
    assert _read(tracked) == "unsaved work"
    assert _read(os.path.join(app_layout.repo_path, "untracked.txt")) == "recorded new"
    safety = _storage(app_layout, subdir="snapshots").list_snapshots(app_layout.app_name)
    assert safety == []


def test_the_code_store_never_shows_up_as_a_run_or_an_app(app_layout, capfd):
    from vmn_exp.core.index import indexed_snapshot

    _bootstrap(app_layout)
    _dirty(app_layout)
    verstr = _create(app_layout, capfd)
    storage = _storage(app_layout)

    assert storage.list_verstrs(app_layout.app_name) == [verstr]
    assert [m["verstr"] for m in storage.list_snapshots(app_layout.app_name)] == [verstr]
    assert list(storage.list_record_names(app_layout.app_name)) == [verstr]
    assert storage.list_apps() == [app_layout.app_name]
    rows = indexed_snapshot(storage, app_layout.app_name, wait=True).rows
    assert [r["verstr"] for r in rows] == [verstr]


def test_start_run_has_no_snapshot_option(app_layout):
    _bootstrap(app_layout)
    with pytest.raises(TypeError):
        start_run(app_layout.app_name, snapshot=False)
