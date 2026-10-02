"""Dev-version capture round-trips: binary edits, odd names, local commits, tar safety."""
import io
import os
import shutil
import subprocess
import tarfile

import pytest
import yaml

from helpers import _bootstrap, _snapshot, extract_dev_verstr
from version_stamp.devversion.untracked import _extract_untracked_tarball


def _path(app_layout, name):
    return os.path.join(app_layout.repo_path, name)


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _discard_changes(app_layout):
    _git(app_layout.repo_path, "checkout", ".")
    _git(app_layout.repo_path, "clean", "-fdq")


def _restore(app_layout, verstr):
    return _snapshot(app_layout.app_name, action="restore", version=verstr)


@pytest.fixture
def stamped(app_layout):
    _bootstrap(app_layout)
    return app_layout


def test_tracked_binary_edit_roundtrips(stamped, capfd):
    path = _path(stamped, "blob.bin")
    with open(path, "wb") as f:
        f.write(b"\x00\x01\x02binary\xff" * 10)
    _git(stamped.repo_path, "add", "blob.bin")
    _git(stamped.repo_path, "commit", "-qm", "add blob")
    _git(stamped.repo_path, "push", "-q")
    edited = b"\x00\xfe\xfdchanged\x00" * 12
    with open(path, "wb") as f:
        f.write(edited)

    verstr = _create(stamped, capfd)
    _discard_changes(stamped)

    assert _restore(stamped, verstr) == 0
    with open(path, "rb") as f:
        assert f.read() == edited


def test_untracked_names_with_unicode_and_quotes_roundtrip(stamped, capfd):
    names = ["é.txt", 'q"x.txt']
    for name in names:
        with open(_path(stamped, name), "w") as f:
            f.write(f"content of {name}")

    verstr = _create(stamped, capfd)
    _discard_changes(stamped)

    assert _restore(stamped, verstr) == 0
    for name in names:
        with open(_path(stamped, name)) as f:
            assert f.read() == f"content of {name}"


def _copy_snapshot_stores(src_repo, dst_repo, app_name):
    for rel in (os.path.join("store", "snapshots", app_name), os.path.join("store", "code")):
        src = os.path.join(src_repo, ".vmn", rel)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst_repo, ".vmn", rel), dirs_exist_ok=True)


def test_unpushed_commit_is_based_on_upstream_and_restores_in_fresh_clone(
    stamped, capfd
):
    upstream = _git(stamped.repo_path, "rev-parse", "HEAD")
    stamped.write_file_commit_and_push(
        "test_repo_0", "local.txt", "local only", push=False
    )
    verstr = _create(stamped, capfd)
    meta_path = os.path.join(
        stamped.repo_path, ".vmn", "store", "snapshots", stamped.app_name, verstr, "metadata.yml"
    )
    with open(meta_path) as f:
        assert yaml.safe_load(f)["base_commit"] == upstream

    clone = stamped.create_new_clone("test_repo_0")
    _git(clone, "config", "user.name", "tester")
    _git(clone, "config", "user.email", "tester@example.com")
    _copy_snapshot_stores(stamped.repo_path, clone, stamped.app_name)
    stamped.set_working_dir(clone)

    assert _restore(stamped, verstr) == 0
    with open(os.path.join(clone, "local.txt")) as f:
        assert f.read() == "local only"


def _tarball(*members):
    buf = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=buf) as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def _file(name, data=b"evil"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _link(name, target, kind):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info, None


@pytest.mark.parametrize(
    "members",
    [
        [_file("../evil")],
        [_file("sub/../../evil")],
        [_file("{abs}/outside")],
        [_link("ln", "../evil", tarfile.SYMTYPE)],
        [_link("ln", "/etc/passwd", tarfile.SYMTYPE)],
        [_link("hl", "../evil", tarfile.LNKTYPE)],
    ],
)
def test_extract_rejects_members_escaping_dest(tmp_path, members):
    dest = tmp_path / "dest"
    dest.mkdir()
    members = [(_with_abs(info, tmp_path), data) for info, data in members]
    with pytest.raises(Exception):
        _extract_untracked_tarball(str(dest), _tarball(*members))
    assert sorted(os.listdir(tmp_path)) == ["dest"]
    assert os.listdir(dest) == []


def _with_abs(info, tmp_path):
    info.name = info.name.replace("{abs}", str(tmp_path))
    return info


def test_extract_keeps_safe_members(tmp_path):
    _extract_untracked_tarball(
        str(tmp_path), _tarball(_file("a/b.txt", b"ok"), _link("a/ln", "b.txt", tarfile.SYMTYPE))
    )
    assert (tmp_path / "a" / "b.txt").read_bytes() == b"ok"
    assert os.readlink(tmp_path / "a" / "ln") == "b.txt"
