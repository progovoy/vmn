"""Dump files: SIGUSR1 and --diag-every write <data-dir>/diag/diag-<ts>-<pid>.json."""
import json
import os
import re
import signal
import threading
import time

import pytest

from vmn_exp.ui import diag
from vmn_exp.ui.diag import dump_files

NAME = re.compile(r"^diag-\d{8}T\d{6}Z-%d\.json$" % os.getpid())


def _wait_for_files(directory, n=1, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.isdir(directory):
            names = [f for f in os.listdir(directory) if f.endswith(".json")]
            if len(names) >= n:
                return sorted(names)
        time.sleep(0.02)
    return []


def test_write_dump_names_the_file_by_utc_time_and_pid(tmp_path):
    path = diag.write_dump(str(tmp_path))
    assert os.path.dirname(path) == str(tmp_path / "diag")
    assert NAME.match(os.path.basename(path))
    with open(path) as f:
        assert json.load(f)["format"] == 1


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="no SIGUSR1 here")
def test_sigusr1_writes_a_dump_and_logs_its_path(tmp_path, capfd):
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signal handlers install on the main thread only")
    previous = diag.install_signal_handler(str(tmp_path))
    try:
        os.kill(os.getpid(), signal.SIGUSR1)
        names = _wait_for_files(str(tmp_path / "diag"))
        time.sleep(0.1)  # the log line follows the write
    finally:
        signal.signal(signal.SIGUSR1, previous)
    assert len(names) == 1 and NAME.match(names[0])
    assert str(tmp_path / "diag" / names[0]) in capfd.readouterr().err


def test_periodic_dumps_keep_the_last_twenty(tmp_path, monkeypatch):
    directory = tmp_path / "diag"
    directory.mkdir()
    for i in range(25):
        (directory / f"diag-20260101T0000{i:02d}Z-1.json").write_text("{}")
    stop = threading.Event()
    thread = diag.start_periodic_dumps(str(tmp_path), 0.05, stop=stop)
    try:
        assert thread.daemon
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            names = os.listdir(directory)
            if any(NAME.match(n) for n in names) and len(names) <= dump_files.KEEP:
                break
            time.sleep(0.02)
    finally:
        stop.set()
        thread.join(5)
    names = sorted(os.listdir(directory))
    assert len(names) == dump_files.KEEP == 20
    assert any(NAME.match(n) for n in names)
    assert "diag-20260101T000000Z-1.json" not in names


def test_ui_parses_diag_every():
    from version_stamp.cli.args import parse_user_commands

    assert parse_user_commands(["ui", "--diag-every", "30"]).diag_every == 30
    assert parse_user_commands(["ui"]).diag_every is None


def test_vmn_exp_ui_installs_the_signal_and_periodic_dumps(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.core.logging import init_stamp_logger, reset_logger
    from vmn_exp.ui.cli import handle_ui

    reset_logger()
    init_stamp_logger()
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: calls.append("serve"))
    monkeypatch.setattr(diag, "install_signal_handler", lambda d: calls.append(("signal", d)))
    monkeypatch.setattr(diag, "start_periodic_dumps",
                        lambda d, every: calls.append(("every", d, every)))
    monkeypatch.setattr(diag, "record_server_options", lambda o: calls.append(("options", o)))
    data_dir = str(tmp_path / "ui_data")
    args = parse_user_commands(["ui", "--data-dir", data_dir, "--no-browser",
                                "--token", "tok-SECRET", "--diag-every", "15"])
    assert handle_ui(args) == 0
    assert ("signal", data_dir) in calls
    assert ("every", data_dir, 15) in calls
    options = [c[1] for c in calls if c[0] == "options"][0]
    assert options["token"] == "tok-SECRET" and options["diag_every"] == 15
    assert calls[-1] == "serve"
