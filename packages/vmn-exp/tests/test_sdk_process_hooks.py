"""The SDK's process-wide hooks (excepthook, atexit finalizer) are installed
at the first run open, not when ``vmn_exp.sdk`` is imported.

Importing the SDK for reading only must leave the process alone; and a run
opened over a buffered storage must be finalized before that storage's exit
flush ships the last lines, not after.
"""
import os
import subprocess
import textwrap
from types import SimpleNamespace

from exp_helpers import _PY, _SRC_PATH

from vmn_exp.core.status import load_run_state
from vmn_exp.sdk.process_hooks import ProcessHooks
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
CODE = "2.0.251-dev.852cb2d.0000000"


class FakeAtexit:
    def __init__(self):
        self.registered = []

    def register(self, func):
        self.registered.append(func)


class Pid:
    def __init__(self, pid=100):
        self.pid = pid

    def __call__(self):
        return self.pid


def _fake_sys():
    seen = []
    return SimpleNamespace(excepthook=lambda *exc: seen.append(exc)), seen


def _install(hooks, fake_sys, fake_atexit, noted):
    hooks.install_once(fake_sys, fake_atexit, finalize=_finalize, note_uncaught=noted.append)


def _finalize():
    pass


def test_install_once_chains_the_previous_excepthook():
    fake_sys, previous_saw = _fake_sys()
    noted = []
    _install(ProcessHooks(Pid()), fake_sys, FakeAtexit(), noted)

    error = KeyError("lr")
    fake_sys.excepthook(KeyError, error, None)

    assert noted == [error]
    assert previous_saw == [(KeyError, error, None)]


def test_install_once_registers_the_finalizer_a_single_time():
    fake_sys, _ = _fake_sys()
    fake_atexit = FakeAtexit()
    hooks = ProcessHooks(Pid())
    _install(hooks, fake_sys, fake_atexit, [])
    hook = fake_sys.excepthook

    _install(hooks, fake_sys, fake_atexit, [])

    assert fake_atexit.registered == [_finalize]
    assert fake_sys.excepthook is hook


def test_a_new_pid_installs_again():
    fake_sys, _ = _fake_sys()
    fake_atexit = FakeAtexit()
    pid = Pid(100)
    hooks = ProcessHooks(pid)
    _install(hooks, fake_sys, fake_atexit, [])

    pid.pid = 101  # a forked child
    _install(hooks, fake_sys, fake_atexit, [])

    assert fake_atexit.registered == [_finalize, _finalize]


def _python(code, env=None):
    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_SRC_PATH, os.environ.get("PYTHONPATH")) if p)
    for name, value in (env or {}).items():
        if value is None:
            full_env.pop(name, None)
        else:
            full_env[name] = value
    return subprocess.run([_PY, "-c", textwrap.dedent(code)], env=full_env,
                          capture_output=True, text=True, timeout=120)


def test_importing_the_sdk_leaves_excepthook_alone():
    proc = _python("""
        import sys
        before = sys.excepthook
        import vmn_exp.sdk
        print("KEPT", sys.excepthook is before)
    """)

    assert proc.returncode == 0, proc.stderr
    assert "KEPT True" in proc.stdout


_ABANDON_ON_A_BUFFER = """
    import atexit, os
    from vmn_exp.sdk import start_run
    # Imported after the SDK, as storage/open.py imports it lazily.
    from vmn_exp.storage.buffered import BufferedRemoteStorage
    from vmn_exp.storage.local import LocalSnapshotStorage

    # Runs where the buffer's exit flush (registered at its import) runs.
    atexit.register(lambda: print("FINALIZED_BEFORE_FLUSH", run._finished, flush=True))

    class RemoteDir(LocalSnapshotStorage):
        def is_remote(self):
            return True

    remote = RemoteDir(os.environ["STORE"], "runs")
    run = start_run("app", storage=BufferedRemoteStorage(remote, os.environ["TMPDIR"], area="runs"),
                    system_metrics=False, heartbeat_interval_sec=3600)
    run.log_note("first")
    run.log_note("last")
    print(run.id, flush=True)
"""


def _git_free_env(tmp_path):
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(
        f"verstr: {CODE}\napp_name: {APP}\n"
        "base_version: 2.0.251\nbase_commit: 852cb2d\nbranch: master\n"
    )
    buffers = tmp_path / "tmp"
    buffers.mkdir()
    env = {"VMN_SNAPSHOT_METADATA": str(meta), "STORE": str(tmp_path / "store"),
           "TMPDIR": str(buffers)}
    for var in ("VMN_WRITER_ID", "VMN_EXP_OFFLINE", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID"):
        env[var] = None
    return env, buffers


def test_the_run_finalizer_is_registered_after_the_storage_exit_flushes(tmp_path):
    env, buffers = _git_free_env(tmp_path)

    proc = _python(_ABANDON_ON_A_BUFFER, env)

    assert proc.returncode == 0, proc.stderr
    verstr = proc.stdout.split()[0]
    assert "FINALIZED_BEFORE_FLUSH True" in proc.stdout
    remote = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    state = load_run_state(remote, APP, verstr)
    assert state["state"] == "finished" and state["exit_code"] == 0, state
    notes = [e["text"] for e in remote.load_merged_log(APP, verstr) if e.get("type") == "note"]
    assert notes == ["first", "last"]
    assert [p.name for p in buffers.iterdir() if p.name.startswith("vmn-log-buffer-")] == []
