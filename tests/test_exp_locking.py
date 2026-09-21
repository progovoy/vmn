"""Where the per-repo vmn lock is held during `exp run` and `start_run`.

The repo lock (`.vmn/vmn.lock`) serializes mutations. `exp run` mutates while it
*creates* an experiment and then does nothing but supervise a child that may
live for hours, so it must hold the lock for the create phase only. These tests
pin both halves of that: the create phase still serializes, and the supervision
phase leaves the repo usable — including by the child's own process tree, which
must contend on the *real* lock file rather than a private one.
"""
import glob
import json
import os
import subprocess
import tempfile
import time

import pytest
from filelock import FileLock, Timeout

from version_stamp.core.experiment_status import load_run_state
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage

# A held lock blocks for as long as we hold it, so "still running after this
# window" is a deterministic observation, not a race.
BLOCKED_WINDOW = 3.0
# Generous but finite: a vmn subprocess that needs longer than this is wedged.
JOIN_TIMEOUT = 120
# Long enough that the child is certainly still alive while we assert.
CHILD_SLEEP = 20


def _lock_path(app_layout):
    return os.path.join(app_layout.repo_path, ".vmn", "vmn.lock")


def _env(app_layout, extra=None):
    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _PROJECT_ROOT
    env.pop("VMN_EXPERIMENT_ID", None)
    env.pop("VMN_APP_NAME", None)
    env.pop("VMN_LOCK_FILE_PATH", None)
    if extra:
        env.update(extra)
    return env


def _vmn_popen(app_layout, argv, env=None):
    return subprocess.Popen(
        [_PY, "-m", "version_stamp.cli.entry"] + list(argv),
        cwd=app_layout.repo_path,
        env=env or _env(app_layout),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _python_popen(app_layout, script, env=None):
    return subprocess.Popen(
        [_PY, "-c", script],
        cwd=app_layout.repo_path,
        env=env or _env(app_layout),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _join(proc, what, timeout=JOIN_TIMEOUT):
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(f"{what} did not finish within {timeout}s (deadlock?)")
    return proc.returncode, out


def _kill(proc):
    if proc.poll() is None:
        proc.kill()
    try:
        proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def _experiments(app_layout):
    return _storage(app_layout).list_snapshots(app_layout.app_name)


def _wait_for(predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    pytest.fail(f"timed out after {timeout}s waiting for {what}")


def _sleep_cmd(seconds):
    return [_PY, "-c", f"import time; time.sleep({seconds})"]


# ---------------------------------------------------------------------------
# the deadlock regression
# ---------------------------------------------------------------------------


def test_nested_exp_run_completes_without_a_lock_redirect(app_layout):
    """A `vmn exp run` inside a `vmn exp run` used to deadlock on the repo lock.

    Deterministic because the inner process either takes the lock or waits for
    it forever; a finite timeout turns the forever case into a clear failure.
    """
    _bootstrap(app_layout)

    proc = _vmn_popen(
        app_layout,
        [
            "exp",
            "run",
            app_layout.app_name,
            "--",
            _PY,
            "-m",
            "version_stamp.cli.entry",
            "exp",
            "run",
            app_layout.app_name,
            "--",
            _PY,
            "-c",
            "print('trial')",
        ],
    )
    rc, out = _join(proc, "nested vmn exp run")
    assert rc == 0, out

    metas = _experiments(app_layout)
    assert len(metas) == 2, [m["verstr"] for m in metas]
    outers = [m for m in metas if not m.get("parent")]
    inners = [m for m in metas if m.get("parent")]
    assert len(outers) == 1 and len(inners) == 1, [
        (m["verstr"], m.get("parent")) for m in metas
    ]
    assert inners[0]["parent"] == outers[0]["verstr"]


# ---------------------------------------------------------------------------
# serialization is restored for the child's process tree
# ---------------------------------------------------------------------------


_DUMP_VMN_ENV = (
    "import json, os; "
    "print(json.dumps({k: v for k, v in os.environ.items() "
    "if k.startswith('VMN_')}))"
)


def _child_vmn_env(app_layout):
    """The VMN_* env a supervised `exp run` child actually sees."""
    proc = _vmn_popen(
        app_layout,
        ["exp", "run", app_layout.app_name, "--", _PY, "-c", _DUMP_VMN_ENV],
    )
    rc, out = _join(proc, "vmn exp run env dump")
    assert rc == 0, out

    child_env = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            child_env = json.loads(line)
    assert child_env is not None, out
    return child_env


def test_child_env_carries_no_lock_redirect(app_layout):
    """The child must not be handed a private lock file path."""
    _bootstrap(app_layout)

    child_env = _child_vmn_env(app_layout)
    assert child_env.get("VMN_EXPERIMENT_ID"), child_env
    assert "VMN_LOCK_FILE_PATH" not in child_env, child_env


def test_a_command_from_the_child_env_contends_on_the_real_lock(app_layout):
    """Run vmn with exactly the env the child gets: it must block on the real
    `.vmn/vmn.lock`. Deterministic: we hold that lock for a fixed window and
    require the process to still be running, then release and require it to
    finish."""
    _bootstrap(app_layout)

    child_env = _child_vmn_env(app_layout)

    lock = FileLock(_lock_path(app_layout))
    lock.acquire()
    grandchild = _vmn_popen(
        app_layout,
        ["exp", "create", app_layout.app_name],
        env=_env(app_layout, child_env),
    )
    try:
        time.sleep(BLOCKED_WINDOW)
        assert grandchild.poll() is None, (
            "a vmn command run with the child's env did not contend on "
            ".vmn/vmn.lock - it is using a different lock file"
        )
    finally:
        lock.release()
    rc, out = _join(grandchild, "vmn exp create from the child env")
    assert rc == 0, out


# ---------------------------------------------------------------------------
# supervision does not block the repo
# ---------------------------------------------------------------------------


def test_supervising_a_child_leaves_the_repo_lock_free(app_layout):
    """`run_state.yml` is published only after the create phase released the
    lock, so waiting for it is a deterministic 'supervision has begun' signal."""
    _bootstrap(app_layout)

    proc = _vmn_popen(
        app_layout,
        ["exp", "run", app_layout.app_name, "--"] + _sleep_cmd(CHILD_SLEEP),
    )
    try:
        _wait_for(
            lambda: any(
                load_run_state(_storage(app_layout), app_layout.app_name, m["verstr"])
                for m in _experiments(app_layout)
            ),
            timeout=60,
            what="the supervised child to start",
        )
        assert proc.poll() is None, "the child exited before we could assert"

        lock = FileLock(_lock_path(app_layout))
        try:
            lock.acquire(timeout=15)
        except Timeout:
            pytest.fail(
                "the repo lock is held for the whole lifetime of the "
                "supervised child"
            )
        lock.release()

        show = _vmn_popen(app_layout, ["show", app_layout.app_name])
        rc, out = _join(show, "vmn show during supervision", timeout=60)
        assert rc == 0, out
        assert proc.poll() is None, "the child exited before we could assert"
    finally:
        _kill(proc)


# ---------------------------------------------------------------------------
# the create phase is still protected
# ---------------------------------------------------------------------------


def test_create_phase_waits_for_the_repo_lock(app_layout):
    _bootstrap(app_layout)

    lock = FileLock(_lock_path(app_layout))
    lock.acquire()
    proc = _vmn_popen(
        app_layout,
        ["exp", "run", app_layout.app_name, "--", _PY, "-c", "print('trial')"],
    )
    try:
        time.sleep(BLOCKED_WINDOW)
        assert proc.poll() is None, "vmn exp run did not wait for the repo lock"
        assert not _experiments(app_layout), (
            "an experiment was created while another process held the repo lock"
        )
    finally:
        lock.release()

    rc, out = _join(proc, "vmn exp run after the lock was released")
    assert rc == 0, out
    assert len(_experiments(app_layout)) == 1


# ---------------------------------------------------------------------------
# the SDK
# ---------------------------------------------------------------------------


_SDK_OPEN_RUN = """
import os, sys, time
from version_stamp.exp import start_run

open_marker = sys.argv[1] if len(sys.argv) > 1 else os.environ["OPEN_MARKER"]
go_marker = os.environ["GO_MARKER"]

run = start_run(os.environ["APP"])
with open(open_marker, "w") as f:
    f.write(run.id)
deadline = time.time() + 60
while not os.path.exists(go_marker) and time.time() < deadline:
    time.sleep(0.1)
run.finish()
print(run.id)
"""


def test_sdk_create_waits_for_the_repo_lock(app_layout):
    _bootstrap(app_layout)

    open_marker = os.path.join(app_layout.base_dir, "sdk_open")
    go_marker = os.path.join(app_layout.base_dir, "sdk_go")
    env = _env(
        app_layout,
        {
            "APP": app_layout.app_name,
            "OPEN_MARKER": open_marker,
            "GO_MARKER": go_marker,
        },
    )

    lock = FileLock(_lock_path(app_layout))
    lock.acquire()
    proc = _python_popen(app_layout, _SDK_OPEN_RUN, env=env)
    try:
        time.sleep(BLOCKED_WINDOW)
        assert proc.poll() is None, "start_run did not wait for the repo lock"
        assert not os.path.exists(open_marker), (
            "start_run created an experiment while another process held the "
            "repo lock"
        )
        assert not _experiments(app_layout)
    finally:
        lock.release()

    _wait_for(
        lambda: os.path.exists(open_marker) or proc.poll() is not None,
        timeout=60,
        what="start_run to open its run once the lock was free",
    )
    with open(go_marker, "w"):
        pass
    rc, out = _join(proc, "the SDK run")
    assert rc == 0, out
    assert len(_experiments(app_layout)) == 1


def test_sdk_releases_the_lock_before_returning_the_run(app_layout):
    _bootstrap(app_layout)

    open_marker = os.path.join(app_layout.base_dir, "sdk_open2")
    go_marker = os.path.join(app_layout.base_dir, "sdk_go2")
    env = _env(
        app_layout,
        {
            "APP": app_layout.app_name,
            "OPEN_MARKER": open_marker,
            "GO_MARKER": go_marker,
        },
    )
    proc = _python_popen(app_layout, _SDK_OPEN_RUN, env=env)
    try:
        _wait_for(
            lambda: os.path.exists(open_marker) or proc.poll() is not None,
            timeout=60,
            what="the SDK run to open",
        )
        assert proc.poll() is None, _join(proc, "the SDK run")[1]

        lock = FileLock(_lock_path(app_layout))
        try:
            lock.acquire(timeout=15)
        except Timeout:
            pytest.fail("start_run holds the repo lock for the life of the run")
        lock.release()
    finally:
        with open(go_marker, "w"):
            pass

    rc, out = _join(proc, "the SDK run")
    assert rc == 0, out


def test_sdk_cold_start_still_works_in_a_fresh_repo(app_layout):
    """No bootstrap: start_run inits the repo and stamps a baseline - the most
    mutating thing the SDK does, and now the thing the lock protects."""
    script = (
        "import os\n"
        "from version_stamp.exp import start_run\n"
        "with start_run(os.environ['APP']) as run:\n"
        "    run.log_metric('acc', 1.0)\n"
        "print(run.id)\n"
    )
    proc = _python_popen(
        app_layout, script, env=_env(app_layout, {"APP": app_layout.app_name})
    )
    rc, out = _join(proc, "the cold-starting SDK run")
    assert rc == 0, out
    assert len(_experiments(app_layout)) == 1


# ---------------------------------------------------------------------------
# no leaked temp locks
# ---------------------------------------------------------------------------


def test_no_temp_run_lock_files_are_created(app_layout):
    """A nested run is what used to materialize the redirected lock file."""
    _bootstrap(app_layout)

    pattern = os.path.join(tempfile.gettempdir(), "vmn-run-*.lock")
    before = set(glob.glob(pattern))

    proc = _vmn_popen(
        app_layout,
        [
            "exp",
            "run",
            app_layout.app_name,
            "--",
            _PY,
            "-m",
            "version_stamp.cli.entry",
            "exp",
            "create",
            app_layout.app_name,
        ],
    )
    rc, out = _join(proc, "vmn exp run")
    assert rc == 0, out

    assert not (set(glob.glob(pattern)) - before), "a temp run lock file was created"
