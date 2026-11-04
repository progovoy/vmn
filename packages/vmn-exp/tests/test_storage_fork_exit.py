"""A raw ``os.fork`` child leaving through ``sys.exit``, a return or
``SystemExit`` runs the atexit handlers it inherited: they must leave the
parent's storage state alone (plan 30, G3 / W3).

* ``buffered.close_all`` ships only the buffers this process created: the
  child never ships the parent's lines under the parent's stream owner, nor
  ``rmtree``s the buffer dir both share. A buffer the child creates, or a
  write it makes through an inherited storage, still ships at its exit.
* ``journal._flush_all`` flushes only this process's journal states: the
  child never takes a ``_JournalState.lock`` a parent thread held at fork.

Each scenario runs in its own interpreter, so forking never touches pytest's.
"""
import os
import subprocess
import sys

import pytest
from exp_helpers import _PY, _SRC_PATH

pytestmark = pytest.mark.skipif(
    not hasattr(os, "fork") or sys.platform == "win32", reason="needs fork"
)

_WAIT_CHILD = r"""
def wait_child(pid, timeout=10):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.WEXITSTATUS(status), time.monotonic() - start
        time.sleep(0.01)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    print("HUNG: the forked child never exited", flush=True)
    os._exit(75)   # not sys.exit: this process's own exit handlers may hang too
"""

_BUFFERED = r"""
import os, sys, time
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.local import LocalSnapshotStorage

ROOT, MODE = sys.argv[1], sys.argv[2]
WRITES = os.path.join(ROOT, "writes.log")
_WRITE = ("put", "save", "create", "append", "delete", "update")


class Remote(LocalSnapshotStorage):
    # Notes which process made each remote write.
    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if callable(attr) and name.startswith(_WRITE):
            with open(WRITES, "a") as f:
                f.write(f"{os.getpid()} {name}\n")
        return attr


def line(i):
    return {"timestamp": "2026-01-01T00:00:00Z", "type": "note", "i": i}


def append(storage, i):
    stream = own_stream(storage, "app", "v")   # <writer>~<the buffer's owner>
    storage.append_log_entry("app", "v", stream, line(i))


def streams():
    by = remote.load_logs_by_writer("app", "v")
    return sorted(sorted(e["i"] for e in entries) for entries in by.values() if entries)


remote = Remote(os.path.join(ROOT, "remote"), "runs")
remote.save("app", "v", {"verstr": "v"}, {})
storage = BufferedRemoteStorage(remote, flush_interval_sec=3600)
for i in range(3):
    append(storage, i)
assert streams() == [[0]], streams()   # 1 and 2 wait in the parent's buffer
buffer_root = storage._buffer_root
""" + _WAIT_CHILD + r"""
pid = os.fork()
if pid == 0:
    if MODE == "own":
        mine = BufferedRemoteStorage(remote, flush_interval_sec=3600)
        append(mine, 100)
        append(mine, 101)   # buffered: ships at exit
        append(storage, 200)  # an inherited storage
        sys.exit(0)
    if MODE == "exit":
        sys.exit(0)
    if MODE == "raise":
        raise SystemExit(0)
    if MODE == "os_exit":
        os._exit(0)
    # MODE == "return": falls off the end of the script, a normal exit
else:
    code, took = wait_child(pid)
    assert code == 0, code
    assert took < 1, f"the child took {took:.1f}s to exit"
    assert os.path.isdir(buffer_root), "the child removed the parent's buffer dir"
    expected = [[0]] + ([[100, 101], [200]] if MODE == "own" else [])
    assert streams() == sorted(expected), streams()
    with open(WRITES) as f:
        by_child = [w for w in f.read().split("\n") if w.startswith(f"{pid} ")]
    if MODE != "own":
        assert by_child == [], by_child
    append(storage, 3)
    buffered.close_all()
    assert sorted(streams()) == sorted([[0, 1, 2, 3]] + expected[1:]), streams()
    print("OK")
"""

_JOURNAL = r"""
import os, sys, threading, time
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.local import LocalSnapshotStorage

ROOT = sys.argv[1]
PUTS = os.path.join(ROOT, "puts.log")


class Sink:
    def put(self, key):
        with open(PUTS, "a") as f:
            f.write(f"{os.getpid()} {key}\n")


def puts_by(pid):
    with open(PUTS) as f:
        rows = [row.split(" ", 1) for row in f.read().splitlines()]
    return [key for who, key in rows if who == str(pid)]


storage = journaled(LocalSnapshotStorage(os.path.join(ROOT, "store"), "runs"), sink=Sink())
storage.save("app", "v", {"verstr": "v"}, {})
state = storage._journal_state
state.pending.append("parent-queued")   # a put that failed: retried later
held, release = threading.Event(), threading.Event()


def hold_the_lock():
    with state.lock:
        held.set()
        release.wait()


holder = threading.Thread(target=hold_the_lock, daemon=True)
holder.start()
assert held.wait(5)
""" + _WAIT_CHILD + r"""
pid = os.fork()
if pid == 0:
    storage.save_file("app", "v", "note.txt", "from the child")
    sys.exit(0)
code, took = wait_child(pid)
release.set()
holder.join()
assert code == 0, code
child = puts_by(pid)
assert len(child) == 1 and "parent-queued" not in child, child
storage.flush_journal()
assert puts_by(os.getpid()).count("parent-queued") == 1, puts_by(os.getpid())
print("OK")
"""


def _run_script(script, tmp_path, *args):
    proc = subprocess.run(
        [_PY, "-c", script, str(tmp_path), *args],
        env=dict(os.environ, PYTHONPATH=_SRC_PATH),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.parametrize("mode", ["exit", "return", "raise", "os_exit"])
def test_a_forked_child_leaves_the_parents_buffer_alone(tmp_path, mode):
    _run_script(_BUFFERED, tmp_path, mode)


def test_a_forked_childs_own_buffers_still_ship_at_its_exit(tmp_path):
    _run_script(_BUFFERED, tmp_path, "own")


def test_a_forked_child_never_takes_a_journal_lock_held_at_fork(tmp_path):
    _run_script(_JOURNAL, tmp_path)
