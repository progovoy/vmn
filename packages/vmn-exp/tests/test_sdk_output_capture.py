"""``start_run(capture_output=True)`` keeps the process's console as ``output.log``.

Capture is at the file-descriptor level, so output a C extension or a
subprocess writes is kept too, and the terminal still gets everything. The
original descriptors are back once the run finishes.
"""
import os
import subprocess

from exp_helpers import _PY, _SRC_PATH, _bootstrap, _storage

from vmn_exp.core.output_log import OUTPUT_LOG_PATH


def _run_python(app_layout, body):
    script = "from vmn_exp.sdk import start_run\nAPP = %r\n%s" % (
        app_layout.app_name,
        body,
    )
    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _SRC_PATH
    env.pop("VMN_EXPERIMENT_ID", None)
    return subprocess.run(
        [_PY, "-c", script],
        cwd=app_layout.repo_path,
        env=env,
        capture_output=True,
        timeout=120,
    )


def _output_log(app_layout, verstr):
    path = _storage(app_layout).artifact_local_path(
        app_layout.app_name, verstr, OUTPUT_LOG_PATH
    )
    if path is None:
        return None
    with open(path, "rb") as f:
        return f.read()


def _verstr(stdout):
    lines = stdout.decode(errors="replace").splitlines()
    return [ln for ln in lines if ln.startswith("ID=")][0][3:]


_BODY = (
    "import os, subprocess, sys\n"
    "run = start_run(APP, capture_output=%s)\n"
    "print('py-stdout')\n"
    "print('py-stderr', file=sys.stderr)\n"
    "os.write(1, b'fd-bytes \\xff\\n')\n"
    "subprocess.run(['echo', 'from-subprocess'])\n"
    "run.finish()\n"
    "print('ID=' + run.id)\n"
    "print('after-finish', file=sys.stderr)\n"
)


def test_capture_output_keeps_stdout_stderr_and_subprocess_output(app_layout):
    _bootstrap(app_layout)
    proc = _run_python(app_layout, _BODY % "True")

    assert proc.returncode == 0, proc.stderr
    verstr = _verstr(proc.stdout)
    log = _output_log(app_layout, verstr)
    for needle in (b"py-stdout", b"py-stderr", b"fd-bytes \xff", b"from-subprocess"):
        assert needle in log, needle
    assert b"after-finish" not in log  # the fds were restored at finish


def test_captured_output_still_reaches_the_real_streams(app_layout):
    _bootstrap(app_layout)
    proc = _run_python(app_layout, _BODY % "True")

    assert proc.returncode == 0, proc.stderr
    assert b"py-stdout" in proc.stdout and b"from-subprocess" in proc.stdout
    assert b"py-stderr" in proc.stderr and b"after-finish" in proc.stderr
    assert b"py-stdout" not in proc.stderr


def test_capture_is_off_by_default(app_layout):
    _bootstrap(app_layout)
    proc = _run_python(app_layout, _BODY % "False")

    assert proc.returncode == 0, proc.stderr
    assert _output_log(app_layout, _verstr(proc.stdout)) is None


def test_output_log_is_uploaded_before_the_run_finishes(app_layout, tmp_path):
    _bootstrap(app_layout)
    body = (
        "import time\n"
        "run = start_run(APP, capture_output=True, heartbeat_interval_sec=1,\n"
        "                sync_interval_sec=1)\n"
        "print('mid-run', flush=True)\n"
        "deadline = time.time() + 30\n"
        "art = None\n"
        "while time.time() < deadline:\n"
        "    art = run._storage.artifact_local_path(APP, run.id, 'outputs/output.log')\n"
        "    if art and b'mid-run' in open(art, 'rb').read():\n"
        "        break\n"
        "    time.sleep(0.2)\n"
        "ok = bool(art) and b'mid-run' in open(art, 'rb').read()\n"
        "run.finish()\n"
        "print('ID=' + run.id)\n"
        "print('UPLOADED=%s' % ok)\n"
    )
    proc = _run_python(app_layout, body)

    assert proc.returncode == 0, proc.stderr
    assert b"UPLOADED=True" in proc.stdout


def test_a_run_ended_by_sigterm_still_leaves_output_log(app_layout):
    _bootstrap(app_layout)
    body = (
        "import os, signal, sys\n"
        "run = start_run(APP, capture_output=True)\n"
        "sys.__stderr__.write('ID=' + run.id + '\\n')\n"
        "print('before-term', flush=True)\n"
        "os.kill(os.getpid(), signal.SIGTERM)\n"
        "import time; time.sleep(30)\n"
    )
    proc = _run_python(app_layout, body)

    assert proc.returncode != 0
    verstr = [
        ln for ln in proc.stderr.decode().splitlines() if ln.startswith("ID=")
    ][0][3:]
    assert b"before-term" in _output_log(app_layout, verstr)
