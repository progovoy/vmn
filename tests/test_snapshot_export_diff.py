"""`vmn snapshot export` and `vmn snapshot diff`: materialize a snapshot's tree."""
import os
import shutil
import subprocess
import tarfile

import pytest
import yaml

from helpers import _bootstrap, _snapshot, extract_dev_verstr


def _write(app_layout, name, content):
    with open(os.path.join(app_layout.repo_path, name), "w") as f:
        f.write(content)


def _snapshot_of(app_layout, capfd, content, name="work.txt"):
    if not os.path.exists(os.path.join(app_layout.repo_path, name)):
        app_layout.write_file_commit_and_push("test_repo_0", name, "committed\n")
    _write(app_layout, name, content)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _run(app_layout, capfd, action, **kwargs):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action=action, **kwargs)
    captured = capfd.readouterr()
    return ret, captured.out, captured.err


@pytest.fixture
def stamped(app_layout):
    _bootstrap(app_layout)
    return app_layout


def test_export_to_a_directory(stamped, capfd, tmp_path):
    _write(stamped, "new.py", "untracked\n")
    verstr = _snapshot_of(stamped, capfd, "snapshot state\n")
    out_dir = str(tmp_path / "exported")

    ret, out, _ = _run(stamped, capfd, "export", version=verstr, output=out_dir)

    assert ret == 0
    assert out.strip().splitlines()[-1] == out_dir
    with open(os.path.join(out_dir, "work.txt")) as f:
        assert f.read() == "snapshot state\n"
    with open(os.path.join(out_dir, "new.py")) as f:
        assert f.read() == "untracked\n"
    with open(os.path.join(out_dir, "vmn_metadata.yml")) as f:
        assert yaml.safe_load(f)["verstr"] == verstr
    assert not os.path.isdir(os.path.join(out_dir, ".git"))


def test_export_defaults_to_a_verstr_tarball(stamped, capfd, tmp_path, monkeypatch):
    verstr = _snapshot_of(stamped, capfd, "snapshot state\n")
    monkeypatch.chdir(tmp_path)

    ret, _, _ = _run(stamped, capfd, "export", latest=True)

    assert ret == 0
    tar_path = tmp_path / f"{verstr}.tar.gz"
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
    assert f"{verstr}/work.txt" in names
    assert f"{verstr}/vmn_metadata.yml" in names
    assert not any("/.git/" in n or n.endswith("/.git") for n in names)


def test_export_refuses_a_snapshot_whose_code_is_gone(stamped, capfd, tmp_path):
    verstr = _snapshot_of(stamped, capfd, "snapshot state\n")
    shutil.rmtree(os.path.join(stamped.repo_path, ".vmn", "store", "code"))
    out_dir = str(tmp_path / "exported")

    ret, out, err = _run(stamped, capfd, "export", version=verstr, output=out_dir)

    assert ret == 1
    assert "code" in out + err
    assert not os.path.exists(out_dir)


def test_diff_defaults_to_the_current_working_state(stamped, capfd):
    verstr = _snapshot_of(stamped, capfd, "SNAPSHOT_SIDE\n")
    _write(stamped, "work.txt", "CURRENT_SIDE\n")

    ret, out, _ = _run(stamped, capfd, "diff", version=verstr)

    assert ret == 0
    assert "-SNAPSHOT_SIDE" in out
    assert "+CURRENT_SIDE" in out
    assert "working_tree.patch" not in out


def test_diff_of_the_current_state_is_identical(stamped, capfd):
    verstr = _snapshot_of(stamped, capfd, "same\n")

    ret, out, _ = _run(stamped, capfd, "diff", version=verstr, to_version="current")

    assert ret == 0
    assert "identical" in out


def test_diff_between_two_snapshots(stamped, capfd):
    v_a = _snapshot_of(stamped, capfd, "SIDE_A\n")
    v_b = _snapshot_of(stamped, capfd, "SIDE_B\n")

    ret, out, _ = _run(stamped, capfd, "diff", version=v_a, to_version=v_b)

    assert ret == 0
    assert "-SIDE_A" in out and "+SIDE_B" in out


def test_diff_resolves_to_refs(stamped, capfd):
    _snapshot_of(stamped, capfd, "SIDE_A\n")
    v_b = _snapshot_of(stamped, capfd, "SIDE_B\n")

    ret, out, _ = _run(stamped, capfd, "diff", version=v_b, to_version="@1")

    assert ret == 0
    assert "-SIDE_B" in out and "+SIDE_A" in out


def test_diff_against_a_stamped_version(stamped, capfd):
    verstr = _snapshot_of(stamped, capfd, "DEV_SIDE\n")
    subprocess.run(["git", "checkout", "."], cwd=stamped.repo_path, check=True)

    ret, out, _ = _run(stamped, capfd, "diff", version=verstr, to_version="0.0.1")

    assert ret == 0
    assert "-DEV_SIDE" in out
    assert "0.0.1" in out and verstr in out


def test_diff_of_an_unknown_to_ref_fails(stamped, capfd):
    verstr = _snapshot_of(stamped, capfd, "state\n")

    ret, out, err = _run(stamped, capfd, "diff", version=verstr, to_version="9.9.9")

    assert ret == 1
    assert "9.9.9" in out + err


def test_diff_with_an_external_tool(stamped, capfd, tmp_path):
    verstr = _snapshot_of(stamped, capfd, "SNAPSHOT_SIDE\n")
    record = tmp_path / "tool_args"
    tool = tmp_path / "difftool.sh"
    tool.write_text(f'#!/bin/sh\ncat "$1/work.txt" "$2/work.txt" > {record}\n')
    tool.chmod(0o755)
    _write(stamped, "work.txt", "CURRENT_SIDE\n")

    ret, _, _ = _run(stamped, capfd, "diff", version=verstr, tool=str(tool))

    assert ret == 0
    assert record.read_text() == "SNAPSHOT_SIDE\nCURRENT_SIDE\n"
