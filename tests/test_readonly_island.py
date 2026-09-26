import subprocess

import pytest

from version_stamp.cli import entry
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


def _repo_on(path, branch):
    (path / ".vmn").mkdir(exist_ok=True)
    for cmd in (
        ["init", "-q"],
        ["checkout", "-q", "-b", branch],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"],
    ):
        subprocess.run(["git", "-C", str(path), *cmd], check=True)


COMMAND_LINES = [
    ["stamp", "-r", "patch", "app"],
    ["release", "app"],
    ["add", "--bm", "build", "app"],
    ["init-app", "app"],
]


@pytest.mark.parametrize("command_line", COMMAND_LINES)
def test_island_branch_blocks_version_creation_before_container_setup(
    tmp_path, monkeypatch, capfd, command_line
):
    _repo_on(tmp_path, "island/x/main")

    def fail_if_initialized(*args, **kwargs):
        pytest.fail("VMNContainer initialized before island guard")

    monkeypatch.setattr(entry, "VMNContainer", fail_if_initialized)
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))

    ret, vmn_ctx = entry.vmn_run(command_line)

    assert ret == 1
    assert vmn_ctx is None
    assert "island branch" in capfd.readouterr().err.lower()
    assert not (tmp_path / ".vmn" / "vmn.lock").exists()


@pytest.mark.parametrize("command_line", COMMAND_LINES)
def test_real_branch_inside_island_is_not_blocked(tmp_path, monkeypatch, command_line):
    _repo_on(tmp_path, "feature/x")
    reached = []

    def record_initialization(*args, **kwargs):
        reached.append(True)
        raise RuntimeError("stop after proving the guard allowed the command")

    monkeypatch.setattr(entry, "VMNContainer", record_initialization)
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))

    ret, _ = entry.vmn_run(command_line)

    assert ret == 1
    assert reached == [True]


def test_island_branch_does_not_block_repository_init(tmp_path, monkeypatch):
    _repo_on(tmp_path, "island/x/main")
    reached = []

    def record_initialization(*args, **kwargs):
        reached.append(True)
        raise RuntimeError("stop after proving the guard allowed init")

    monkeypatch.setattr(entry, "VMNContainer", record_initialization)
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))

    ret, _ = entry.vmn_run(["init"])

    assert ret == 1
    assert reached == [True]
