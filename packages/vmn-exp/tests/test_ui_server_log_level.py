"""`vmn-exp ui` doesn't run its libraries at DEBUG: vmn's logger setup puts the
root logger at DEBUG, so botocore built a few dozen LogRecords per S3 call
that every handler then dropped (6% of a client's GIL time during a cold
load). Without --debug the server's root logger is at INFO; with it, vmn's
debug lines stay on."""
import logging

import pytest

pytest.importorskip("fastapi")
from version_stamp.core.logging import VMN_LOGGER  # noqa: E402


@pytest.fixture(autouse=True)
def _root_level():
    root = logging.getLogger()
    level = root.level
    yield
    root.setLevel(level)


def _levels_at_serve(tmp_path, monkeypatch, flags):
    from version_stamp.cli.args import parse_user_commands
    from version_stamp.core.logging import init_stamp_logger, reset_logger
    from vmn_exp.ui.cli import handle_ui

    seen = {}

    def serve(*a, **k):
        seen["botocore"] = logging.getLogger("botocore.endpoint").isEnabledFor(logging.DEBUG)
        seen["vmn"] = VMN_LOGGER.isEnabledFor(logging.DEBUG)

    reset_logger()
    args = parse_user_commands(
        flags + ["ui", "--data-dir", str(tmp_path / "ui_data"), "--no-browser"])
    init_stamp_logger(debug=args.debug)  # as vmn_run does before dispatching ui
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("uvicorn.run", serve)

    assert handle_ui(args) == 0
    return seen


def test_the_server_builds_no_library_debug_records(tmp_path, monkeypatch):
    seen = _levels_at_serve(tmp_path, monkeypatch, [])

    assert seen == {"botocore": False, "vmn": False}


def test_debug_keeps_vmn_debug_lines(tmp_path, monkeypatch):
    seen = _levels_at_serve(tmp_path, monkeypatch, ["--debug"])

    assert seen["vmn"] is True
