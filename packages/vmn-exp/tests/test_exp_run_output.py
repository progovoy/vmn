"""`vmn-exp run` keeps the child's console output as the ``output.log`` artifact.

The terminal still gets every byte live (stdout to stdout, stderr to stderr);
the run keeps a size-capped combined copy, uploaded while the child runs and
once more when it ends — whatever ended it.
"""
import signal
import subprocess
import time

from exp_helpers import _PY, _bootstrap, _exp, _storage, extract_dev_verstr

from vmn_exp.core.output_log import OUTPUT_CAP_ENV, OUTPUT_LOG_NAME

from test_fix_exp_run_signals import (
    _finish,
    _start_supervisor,
    _wait_for_live_run,
)

_CAP_0_01_MB = int(0.01 * 1024 * 1024)

_PRINT_BOTH = (
    "import sys\n"
    "print('to-stdout', flush=True)\n"
    "print('to-stderr', file=sys.stderr, flush=True)\n"
)


def _run(app_layout, capfd, script, extra_args=None):
    capfd.readouterr()
    code = _exp(
        app_layout.app_name,
        action="run",
        run_cmd=[_PY, "-c", script],
        extra_args=extra_args,
    )
    out, err = capfd.readouterr()
    return code, extract_dev_verstr(out), out, err


def _output_log(app_layout, verstr):
    path = _storage(app_layout).artifact_local_path(
        app_layout.app_name, verstr, OUTPUT_LOG_NAME
    )
    if path is None:
        return None
    with open(path, "rb") as f:
        return f.read()


def test_stdout_and_stderr_reach_the_terminal_and_output_log(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr, out, err = _run(app_layout, capfd, _PRINT_BOTH)

    assert code == 0
    # (the supervisor's own "running <cmd>" line quotes the script: match lines)
    assert "to-stdout" in out.splitlines() and "to-stdout" not in err.splitlines()
    assert "to-stderr" in err.splitlines() and "to-stderr" not in out.splitlines()
    log = _output_log(app_layout, verstr)
    assert b"to-stdout\n" in log and b"to-stderr\n" in log


def test_output_log_gets_an_artifact_log_entry(app_layout, capfd):
    _bootstrap(app_layout)
    _, verstr, _, _ = _run(app_layout, capfd, _PRINT_BOTH)

    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    entries = [e for e in log if e.get("type") == "artifact"]
    assert [e["path"] for e in entries] == [OUTPUT_LOG_NAME]
    assert entries[0]["size"] == len(_output_log(app_layout, verstr))


def test_the_cap_flag_bounds_output_log(app_layout, capfd):
    _bootstrap(app_layout)
    script = "import sys\nfor i in range(2000): print('x' * 99)\nprint('LAST')\n"
    _, verstr, out, _ = _run(
        app_layout, capfd, script, extra_args=["--output-cap-mb", "0.01"]
    )

    log = _output_log(app_layout, verstr)
    assert len(log) < _CAP_0_01_MB + 100  # + the omission marker
    assert log.endswith(b"LAST\n")
    assert b"bytes of output omitted" in log
    assert out.count("x" * 99) == 2000  # the terminal is never capped


def test_the_cap_env_var_is_the_fallback(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv(OUTPUT_CAP_ENV, "0.01")
    script = "for i in range(2000): print('y' * 99)\n"
    _, verstr, _, _ = _run(app_layout, capfd, script)
    assert len(_output_log(app_layout, verstr)) < _CAP_0_01_MB + 100


def test_non_utf8_output_is_kept_byte_for_byte(app_layout, capfd):
    _bootstrap(app_layout)
    script = (
        "import os\n"
        "os.write(1, b'caf\\xe9 \\xff\\xfe end\\n')\n"
        "os.write(2, b'err \\x80\\n')\n"
    )
    code, verstr, _, _ = _run(app_layout, capfd, script)

    assert code == 0
    log = _output_log(app_layout, verstr)
    assert b"caf\xe9 \xff\xfe end\n" in log
    assert b"err \x80\n" in log


def test_no_capture_output_opts_out(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr, out, err = _run(
        app_layout, capfd, _PRINT_BOTH, extra_args=["--no-capture-output"]
    )

    assert code == 0
    assert "to-stdout" in out and "to-stderr" in err
    assert _output_log(app_layout, verstr) is None


def test_a_failing_child_still_leaves_its_traceback_in_output_log(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr, _, err = _run(app_layout, capfd, "raise SystemExit('boom-exit')")

    assert code == 1
    assert "boom-exit" in err
    assert b"boom-exit" in _output_log(app_layout, verstr)


def test_output_log_is_uploaded_while_the_child_still_runs(app_layout, tmp_path):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    child = (
        "import time\n"
        "print('early-line', flush=True)\n"
        f"open({marker!r}, 'w').close()\n"
        "time.sleep(60)\n"
    )
    proc = _start_supervisor_with_args(app_layout, child, ["--sync-interval", "1"])
    try:
        verstr, _ = _wait_for_live_run(app_layout, marker)
        deadline = time.time() + 30
        log = None
        while time.time() < deadline:
            log = _output_log(app_layout, verstr)
            if log and b"early-line" in log:
                break
            time.sleep(0.2)
        assert log and b"early-line" in log
    finally:
        proc.send_signal(signal.SIGTERM)
        _finish(proc)


def test_a_signalled_run_still_leaves_output_log(app_layout, tmp_path):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    child = (
        "import time\n"
        "print('before-signal', flush=True)\n"
        f"open({marker!r}, 'w').close()\n"
        "time.sleep(60)\n"
    )
    proc = _start_supervisor(app_layout, child)
    verstr, _ = _wait_for_live_run(app_layout, marker)

    proc.send_signal(signal.SIGTERM)
    out = _finish(proc)

    assert proc.returncode == 128 + signal.SIGTERM, out
    assert "before-signal" in out  # the terminal got it too
    assert b"before-signal" in _output_log(app_layout, verstr)


def test_show_mentions_output_log(app_layout, capfd):
    _bootstrap(app_layout)
    _, verstr, _, _ = _run(app_layout, capfd, _PRINT_BOTH)

    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    assert f"Output:    {OUTPUT_LOG_NAME}" in out


def _start_supervisor_with_args(app_layout, child_script, extra):
    from test_fix_exp_run_signals import _env

    return subprocess.Popen(
        [_PY, "-m", "vmn_exp.cli", "exp", "run", app_layout.app_name, *extra,
         "--", _PY, "-c", child_script],
        cwd=app_layout.repo_path,
        env=_env(app_layout),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

