import pytest

from version_stamp.cli import entry
from version_stamp.cli.worktrees import WORKTREE_READONLY_MARKER
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


@pytest.mark.parametrize(
    "command_line",
    [
        ["stamp", "-r", "patch", "app"],
        ["release", "app"],
        ["add", "--bm", "build", "app"],
        ["init-app", "app"],
    ],
)
def test_readonly_island_blocks_version_creation_before_container_setup(
    tmp_path, monkeypatch, capfd, command_line
):
    vmn_dir = tmp_path / ".vmn"
    vmn_dir.mkdir()
    (vmn_dir / WORKTREE_READONLY_MARKER).touch()

    def fail_if_initialized(*args, **kwargs):
        pytest.fail("VMNContainer initialized before readonly guard")

    monkeypatch.setattr(entry, "VMNContainer", fail_if_initialized)
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))

    ret, vmn_ctx = entry.vmn_run(command_line)

    assert ret == 1
    assert vmn_ctx is None
    assert "version creation is disabled" in capfd.readouterr().err.lower()
    assert not (vmn_dir / "vmn.lock").exists()


def test_readonly_island_does_not_block_repository_init(tmp_path, monkeypatch):
    vmn_dir = tmp_path / ".vmn"
    vmn_dir.mkdir()
    (vmn_dir / WORKTREE_READONLY_MARKER).touch()
    initialized = []

    def record_initialization(*args, **kwargs):
        initialized.append(True)
        raise RuntimeError("stop after proving the guard allowed init")

    monkeypatch.setattr(entry, "VMNContainer", record_initialization)
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))

    ret, _ = entry.vmn_run(["init"])

    assert ret == 1
    assert initialized == [True]
