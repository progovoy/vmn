"""A record lock keeps one fd per lock file open, and still excludes other
processes: across a removed and recreated lock file, in a fork's child, and
past the open-fd cap."""
import os
import shutil
import subprocess
import sys

import pytest

from vmn_exp.storage import ship_state

_PROBE = """import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
"""


def _held_elsewhere(path):
    """Whether another process finds *path*'s lock file locked."""
    return subprocess.run([sys.executable, "-c", _PROBE, path]).returncode == 1


def _path(record, name="state.lock"):
    return os.path.join(str(record), ship_state.SHIP_DIR, name)


def test_a_held_lock_excludes_another_process_and_a_released_one_does_not(tmp_path):
    with ship_state.state_lock(str(tmp_path)):
        assert _held_elsewhere(_path(tmp_path))
    assert not _held_elsewhere(_path(tmp_path))


def test_a_lock_taken_again_after_its_file_was_removed_locks_the_new_file(tmp_path):
    with ship_state.state_lock(str(tmp_path)):
        pass
    shutil.rmtree(os.path.join(str(tmp_path), ship_state.SHIP_DIR))

    with ship_state.state_lock(str(tmp_path)):
        assert _held_elsewhere(_path(tmp_path))


def test_a_fork_child_does_not_share_the_parents_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(ship_state, "LOCK_WAIT_SEC", 0.2)
    with ship_state.state_lock(str(tmp_path)):
        pass  # the parent's fd is open now, and the child inherits it
    held, go = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.read(held, 1)
        try:
            with ship_state.state_lock(str(tmp_path)):
                os._exit(0)
        except RuntimeError:
            os._exit(1)
    with ship_state.state_lock(str(tmp_path)):
        os.write(go, b"x")
        _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 1


def test_open_fds_stay_under_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ship_state, "_MAX_OPEN_FDS", 3)
    for i in range(6):
        with ship_state.state_lock(str(tmp_path / str(i))):
            pass
    assert len(ship_state._FDS) <= 3
    with ship_state.state_lock(str(tmp_path / "0")):
        assert _held_elsewhere(_path(tmp_path / "0"))


@pytest.mark.parametrize("lock", [ship_state.ship_lock, ship_state.append_lock,
                                  ship_state.owner_lock])
def test_every_record_lock_is_reentrant_in_a_thread(tmp_path, lock):
    name = {ship_state.ship_lock: "lock", ship_state.append_lock: "append.lock",
            ship_state.owner_lock: "owner.lock"}[lock]
    with lock(str(tmp_path)):
        with lock(str(tmp_path)):
            assert _held_elsewhere(_path(tmp_path, name))
        assert _held_elsewhere(_path(tmp_path, name))
    assert not _held_elsewhere(_path(tmp_path, name))


def test_a_failure_right_after_the_flock_leaves_the_lock_free(tmp_path, monkeypatch):
    with ship_state.state_lock(str(tmp_path)):
        pass  # the fd is cached now

    def stale(path, *a, **k):  # an NFS record deleted from another host
        raise OSError(116, "Stale file handle", path)

    with monkeypatch.context() as m:
        m.setattr(ship_state.os, "stat", stale)
        with pytest.raises(OSError):
            with ship_state.state_lock(str(tmp_path)):
                pass
    assert not _held_elsewhere(_path(tmp_path))


def test_a_lock_on_a_network_filesystem_keeps_no_fd_open(tmp_path, monkeypatch):
    monkeypatch.setattr(ship_state, "filesystem_type", lambda path: "nfs")
    with ship_state.state_lock(str(tmp_path)):
        assert _held_elsewhere(_path(tmp_path))
    assert _path(tmp_path) not in ship_state._FDS
    assert not _held_elsewhere(_path(tmp_path))
