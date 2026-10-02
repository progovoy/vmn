"""Export and diff never hand out a half-applied or polluted tree: failed
patches fail the export, both diff paths materialize the same clean trees, and
a broken ``git diff`` is an error rather than "identical"."""
import os
import subprocess
from types import SimpleNamespace

import pytest

from helpers import _bootstrap, _snapshot, extract_dev_verstr
from version_stamp.core.logging import ensure_logger
from version_stamp.devversion import materialize


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


def _snapshot_of(app_layout, capfd, content):
    work = os.path.join(app_layout.repo_path, "work.txt")
    if not os.path.exists(work):
        app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "committed\n")
    _write(work, content)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _run(app_layout, capfd, action, **kwargs):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action=action, **kwargs)
    captured = capfd.readouterr()
    return ret, captured.out + captured.err


@pytest.fixture
def stamped(app_layout):
    _bootstrap(app_layout)
    return app_layout


def _corrupt_working_tree_patch(app_layout):
    code_root = os.path.join(app_layout.repo_path, ".vmn", "store", "code")
    corrupted = 0
    for dirpath, _, filenames in os.walk(code_root):
        for name in filenames:
            if "working_tree" in name:
                _write(os.path.join(dirpath, name), "garbage that is no diff\n")
                corrupted += 1
    assert corrupted


def test_export_fails_when_the_snapshot_patches_do_not_apply(stamped, capfd, tmp_path):
    verstr = _snapshot_of(stamped, capfd, "snapshot state\n")
    _corrupt_working_tree_patch(stamped)
    out_dir = str(tmp_path / "exported")

    ret, out = _run(stamped, capfd, "export", version=verstr, output=out_dir)

    assert ret != 0
    assert "working_tree" in out
    assert not os.path.exists(out_dir)


def _listing_tool(tmp_path):
    record = tmp_path / "tool_args"
    tool = tmp_path / "difftool.sh"
    tool.write_text(
        "#!/bin/sh\n"
        f'echo "$1" > {record}\necho "$2" >> {record}\n'
        f'ls -a "$1" "$2" >> {record}\n'
        f'cat "$1/work.txt" "$2/work.txt" >> {record}\n'
    )
    tool.chmod(0o755)
    return str(tool), record


def test_external_tool_gets_trees_without_git_or_vmn_metadata(stamped, capfd, tmp_path):
    verstr = _snapshot_of(stamped, capfd, "SNAPSHOT_SIDE\n")
    tool, record = _listing_tool(tmp_path)

    ret, _ = _run(stamped, capfd, "diff", version=verstr, tool=tool)

    assert ret == 0
    listing = record.read_text()
    assert "SNAPSHOT_SIDE" in listing
    assert ".git\n" not in listing
    assert "vmn_metadata.yml" not in listing


def test_external_tool_diff_of_a_ref_with_itself_gets_two_dirs(stamped, capfd, tmp_path):
    verstr = _snapshot_of(stamped, capfd, "SAME\n")
    tool, record = _listing_tool(tmp_path)

    ret, _ = _run(stamped, capfd, "diff", version=verstr, to_version=verstr, tool=tool)

    assert ret == 0
    left, right = record.read_text().splitlines()[:2]
    assert left != right
    assert record.read_text().count("SAME\n") == 2


def _plain_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ["init", "-q"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
         "--allow-empty", "-m", "base"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True)
    _write(str(repo / "work.txt"), "committed\n")
    subprocess.run(["git", "add", "work.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "w"],
        cwd=repo, check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    return SimpleNamespace(
        vmn_root_path=str(repo), name="app",
        backend=SimpleNamespace(changeset=lambda: head),
    )


def test_external_tool_falls_back_to_head_for_a_base_less_side(tmp_path):
    ensure_logger()
    vcs = _plain_repo(tmp_path)
    tool, record = _listing_tool(tmp_path)

    ret = materialize._diff_with_external_tool(
        tool, vcs, "a", {"verstr": "a"}, {}, "b", {"verstr": "b"}, {}
    )

    assert ret == 0
    assert record.read_text().count("committed\n") == 2


def test_render_tree_diff_reports_a_failing_git_diff(tmp_path, monkeypatch):
    ensure_logger()
    vcs = _plain_repo(tmp_path)
    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if "--no-index" in cmd:
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="boom")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(materialize.subprocess, "run", run)

    text, err = materialize.render_tree_diff(
        vcs, "a", {"verstr": "a"}, {}, "b", {"verstr": "b"}, {}
    )

    assert err is not None
    assert "boom" in err
