"""snapshot.export.export_tree: the directory-or-tarball export flow."""
import os
import tarfile

import pytest

from version_stamp.snapshot import export

RECORD = ({"verstr": "0.0.1-dev.a.b"}, {})


@pytest.fixture
def materialize(monkeypatch):
    calls = []

    def fake(vcs, metadata, patches, dest):
        calls.append(dest)
        os.makedirs(os.path.join(dest, ".git"), exist_ok=True)
        with open(os.path.join(dest, "code.py"), "w") as f:
            f.write("x = 1\n")
        return fake.err

    fake.err = None
    fake.calls = calls
    monkeypatch.setattr(export, "_materialize_workdir", fake)
    return fake


def _write_extra(dest):
    with open(os.path.join(dest, "extra.yml"), "w") as f:
        f.write("k: v\n")


def test_directory_export_strips_git_and_adds_extra_files(tmp_path, materialize):
    out = str(tmp_path / "out")
    assert export.export_tree(None, RECORD, "name", out, _write_extra) == (out, None)
    assert sorted(os.listdir(out)) == ["code.py", "extra.yml"]


def test_tarball_export_archives_under_the_name(tmp_path, materialize):
    out = str(tmp_path / "out.tgz")
    assert export.export_tree(None, RECORD, "name", out, _write_extra) == (out, None)
    with tarfile.open(out) as tar:
        names = sorted(tar.getnames())
    assert names == ["name", "name/code.py", "name/extra.yml"]
    assert not os.path.exists(materialize.calls[0])


def test_default_output_is_a_tarball_in_the_cwd(tmp_path, monkeypatch, materialize):
    monkeypatch.chdir(tmp_path)
    assert export.export_tree(None, RECORD, "name") == ("name.tar.gz", None)
    assert os.path.isfile(tmp_path / "name.tar.gz")


def test_failed_directory_export_removes_the_new_dir(tmp_path, materialize):
    materialize.err = 1
    out = str(tmp_path / "out")
    called = []
    assert export.export_tree(None, RECORD, "name", out, called.append) == (out, 1)
    assert not os.path.exists(out)
    assert called == []


def test_export_tree_is_exposed_through_the_api():
    from version_stamp import api

    assert api.export_tree is export.export_tree
