"""First-run experience: an expected auto-init must not look like a failure.

Cold start is a documented feature — the first `exp create`/`exp run`/
`start_run` in a fresh repo initializes tracking and stamps a 0.0.0 baseline.
It used to announce itself with two error-level messages ("vmn tracking is not
yet initialized. Run vmn init", "Untracked app. Run vmn init-app first") and
then succeed, so a first-time user's first impression was a crash that wasn't
one. These pin the messaging without weakening the genuine error paths.

Assertions are on captured stdout/stderr rather than ``caplog``: vmn logs
through its own configured handlers, which ``caplog`` does not observe, and the
text on the terminal is the thing the user actually reacts to.
"""
import os
import subprocess

from helpers import (
    _PROJECT_ROOT,
    _PY,
    _exec_script,
    _experiment,
    _run_vmn_init,
    _show,
)

_SCARY = ("Untracked app", "not yet initialized")


def test_cli_cold_start_says_nothing_scary(app_layout, capfd):
    """`vmn exp create` in a fresh repo: succeeds, and says so calmly."""
    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="first ever") == 0
    out, err = capfd.readouterr()

    combined = out + err
    for phrase in _SCARY:
        assert phrase not in combined, combined
    assert "[ERROR]" not in combined, combined


def test_cli_cold_start_announces_the_new_app(app_layout, capfd):
    """A typo'd app name becomes a permanent tag, so creation must be visible."""
    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="first ever") == 0
    out, err = capfd.readouterr()

    combined = out + err
    assert app_layout.app_name in combined, combined
    assert "0.0.0" in combined, combined


def test_a_second_run_does_not_announce_initialization(app_layout, capfd):
    assert _experiment(app_layout.app_name, note="first") == 0
    capfd.readouterr()

    assert _experiment(app_layout.app_name, note="second") == 0
    out, err = capfd.readouterr()

    combined = out + err
    assert "Auto-initializing" not in combined, combined
    assert "[ERROR]" not in combined, combined


def test_sdk_cold_start_says_nothing_scary(app_layout):
    """The SDK path must be as quiet as the CLI one, in a bare process."""
    script = _exec_script(
        app_layout,
        "sdk_cold.py",
        "from version_stamp.exp import start_run\n"
        "with start_run('sdk_quiet_app') as run:\n"
        "    run.log_metric('loss', 0.1)\n"
        "    print('OK', run.id)\n",
    )
    env = dict(
        os.environ,
        PYTHONPATH=_PROJECT_ROOT,
        VMN_WORKING_DIR=app_layout.repo_path,
    )
    proc = subprocess.run(
        [_PY, script],
        cwd=app_layout.repo_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout + proc.stderr
    assert "OK" in combined
    for phrase in _SCARY:
        assert phrase not in combined, combined


def test_a_genuinely_untracked_app_still_reports_an_error(app_layout, capfd):
    """The suppression must be scoped to auto-init, not global.

    `vmn show` cannot auto-create anything, so the error telling the user what
    to run has to survive.
    """
    _run_vmn_init()
    capfd.readouterr()
    err_code = _show("no_such_app")
    out, err = capfd.readouterr()

    assert err_code != 0
    assert "[ERROR]" in out + err, "the real error path went silent"
