"""Every line ``vmn-exp ui`` writes to stderr starts with a UTC timestamp and
its level: vmn's own warnings (once, not again through the root logger),
the vmn_exp modules', uvicorn's, a thread's uncaught exception and the
diagnostic dump's notice. Without them an operator could not line a
warning up with a dump or a metrics graph."""
import logging
import re
import threading

import pytest

pytest.importorskip("fastapi")
from version_stamp.core.logging import VMN_LOGGER  # noqa: E402

STAMP = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z"


@pytest.fixture(autouse=True)
def _root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _boom():
    raise RuntimeError("thread boom")


def _serve_logging_everything(tmp_path):
    def serve(*a, **k):
        import uvicorn

        from vmn_exp.ui.diag import dump_files

        uvicorn.Config(*a, **k)  # configures uvicorn's loggers as uvicorn.run does
        VMN_LOGGER.warning("vmn says hi")
        logging.getLogger("vmn_exp.ui.refresher").warning("refresher says hi")
        logging.getLogger("uvicorn.error").error("uvicorn says hi")
        thread = threading.Thread(target=_boom, name="vmn-ui-test")
        thread.start()
        thread.join()
        dump_files._write_and_log(str(tmp_path / "ui_data"))

    return serve


def _stderr_of_a_server(tmp_path, monkeypatch, capfd):
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.core.logging import init_stamp_logger, reset_logger
    from vmn_exp.ui.cli import handle_ui

    reset_logger()
    init_stamp_logger()  # as vmn_run does before dispatching ui
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("uvicorn.run", _serve_logging_everything(tmp_path))
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    args = parse_user_commands(["ui", "--data-dir", str(tmp_path / "ui_data"), "--no-browser"])
    capfd.readouterr()
    assert handle_ui(args) == 0
    return capfd.readouterr().err


def _line_with(err, text):
    lines = [line for line in err.splitlines() if text in line]
    assert len(lines) == 1, (text, err)
    return lines[0]


@pytest.mark.parametrize("text, level", [
    ("vmn says hi", "WARNING"),
    ("refresher says hi", "WARNING"),
    ("uvicorn says hi", "ERROR"),
    ("vmn-ui-test", "ERROR"),
    ("diagnostic dump written to", None),
])
def test_each_server_line_starts_with_a_timestamp(tmp_path, monkeypatch, capfd, text, level):
    err = _stderr_of_a_server(tmp_path, monkeypatch, capfd)

    line = _line_with(err, text)

    assert re.match(STAMP + (rf" \[{level}\] " if level else " "), line), line


def test_a_thread_exception_is_logged_with_its_traceback(tmp_path, monkeypatch, capfd):
    err = _stderr_of_a_server(tmp_path, monkeypatch, capfd)

    assert "RuntimeError: thread boom" in err
    assert "Exception in thread" not in err  # the stdlib's untimestamped print
