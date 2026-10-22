"""SIGUSR2 dumps every thread's stack from C (``faulthandler``): it works when
the server's main thread never gets to run a Python signal handler — a busy
interpreter, a C call holding the GIL — where the SIGUSR1 JSON dump cannot,
and ``vmn-exp ui diag --pid`` falls back to it."""
import os
import signal
import subprocess
import sys
import textwrap
import time
import types

import pytest

pytestmark = pytest.mark.skipif(not hasattr(signal, "SIGUSR2"), reason="POSIX signals")

SRC = [os.path.join(os.path.dirname(__file__), "..", "src"),
       os.path.join(os.path.dirname(__file__), "..", "..", "vmn-exp-sdk", "src"),
       os.path.join(os.path.dirname(__file__), "..", "..", "vmn", "src")]


def _server(tmp_path, body):
    """A process that installs the stack dump, says READY, then runs *body*."""
    script = textwrap.dedent(f"""
        import sys
        from vmn_exp.ui.diag.stacks import install_stack_dump
        install_stack_dump({str(tmp_path)!r})
        print("READY", flush=True)
    """) + textwrap.dedent(body)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(os.path.abspath(p) for p in SRC))
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, env=env, text=True)
    assert proc.stdout.readline().strip() == "READY"
    return proc


def _stacks_file(tmp_path, pid):
    return tmp_path / "diag" / f"stacks-{pid}.log"


def _wait_for(path, needle, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and needle in path.read_text(errors="replace"):
            return True
        time.sleep(0.05)
    return False


def test_sigusr2_dumps_stacks_while_the_main_thread_holds_the_gil(tmp_path):
    # A catastrophic regex: seconds in C with the GIL held, no bytecode run,
    # so no Python-level signal handler could answer meanwhile.
    proc = _server(tmp_path, """
        import re
        re.match(r"(a+)+$", "a" * 27 + "b")
    """)
    try:
        time.sleep(0.3)
        os.kill(proc.pid, signal.SIGUSR2)
        assert _wait_for(_stacks_file(tmp_path, proc.pid), "File", 2.0)
        assert proc.poll() is None  # still inside the regex: answered from C
    finally:
        proc.kill()
        proc.wait()


def test_diag_pid_falls_back_to_the_stack_dump(tmp_path, capsys):
    from vmn_exp.ui import diag_cli

    # No SIGUSR1 handler that answers: the JSON dump never comes.
    proc = _server(tmp_path, """
        import signal, time
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        def waiting_forever():
            time.sleep(60)
        waiting_forever()
    """)
    out = tmp_path / "out" / "stacks.txt"
    args = types.SimpleNamespace(diag_pid=proc.pid, diag_wait=0.5, diag_output=str(out),
                                 data_dir=str(tmp_path), config=None, db=None)
    try:
        assert diag_cli._from_pid(args) == 0
    finally:
        proc.kill()
        proc.wait()
    assert "waiting_forever" in out.read_text()
    assert str(out) in capsys.readouterr().out
