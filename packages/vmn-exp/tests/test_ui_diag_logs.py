"""The logs section: the last warnings/errors the server logged (with their
exception), per-(logger, level) counts since start, and a small ring of
vmn_exp INFO progress lines. Capturing never raises and never does I/O."""
import logging

import pytest

from vmn_exp.ui import diag
from vmn_exp.ui.diag import logs, registry


@pytest.fixture(autouse=True)
def _isolated_sections(monkeypatch):
    monkeypatch.setattr(registry, "_SECTIONS", dict(registry._SECTIONS))


def _captured(name="diag.logs.test", **kwargs):
    handler = logs.LogCapture(**kwargs)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers[:] = [handler]
    logger.propagate = False
    return logger, handler


def test_a_warning_and_an_error_land_with_their_exception():
    logger, handler = _captured()
    logger.warning("store slow: %s", "s3")
    try:
        raise ValueError("bad thing")
    except ValueError:
        logger.exception("refresh failed")
    recent = handler.section()["recent"]
    assert [r["level"] for r in recent] == ["WARNING", "ERROR"]
    first, second = recent
    assert first["message"] == "store slow: s3" and first["logger"] == "diag.logs.test"
    assert first["exc_type"] is None and first["thread"]
    assert isinstance(first["at"], float)
    assert second["exc_type"] == "ValueError" and second["exc_message"] == "bad thing"


def test_info_and_debug_stay_out_of_the_recent_ring():
    logger, handler = _captured()
    logger.info("progress")
    logger.debug("noise")
    assert handler.section()["recent"] == []


def test_counts_are_per_logger_and_level():
    logger, handler = _captured()
    for _ in range(3):
        logger.warning("w")
    logger.error("e")
    counts = {(c["logger"], c["level"]): c["count"] for c in handler.section()["counts"]}
    assert counts == {("diag.logs.test", "WARNING"): 3, ("diag.logs.test", "ERROR"): 1}


def test_the_rings_are_bounded_and_messages_truncated():
    logger, handler = _captured(ring=3)
    for i in range(10):
        logger.warning("x" * 2000 + str(i))
    recent = handler.section()["recent"]
    assert len(recent) == 3
    assert len(recent[-1]["message"]) <= logs.MAX_MESSAGE + 3


def test_vmn_exp_info_lines_go_to_their_own_small_ring():
    logger, handler = _captured("vmn_exp.ui.store_upkeep_test", info_ring=2)
    other = logging.getLogger("diag.logs.somelib")
    other.setLevel(logging.DEBUG)
    other.handlers[:] = [handler]
    other.propagate = False
    for i in range(5):
        logger.info("upkeep %d", i)
    other.info("not ours")
    section = handler.section()
    assert [r["message"] for r in section["info"]] == ["upkeep 3", "upkeep 4"]
    assert section["recent"] == []


def test_a_broken_record_never_raises():
    logger, handler = _captured()
    logger.warning("%d items", "not-a-number")
    recent = handler.section()["recent"]
    assert len(recent) == 1 and "%d items" in recent[0]["message"]


def test_install_is_idempotent_and_the_dump_has_the_section():
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        first = logs.install_log_capture()
        second = logs.install_log_capture()
        assert first is second
        assert root.handlers.count(first) == 1
        diag.install_default_sections()
        logging.getLogger("vmn_exp.diag_test").warning("visible in the dump")
        section = diag.build_dump()["sections"]["logs"]
        assert any(r["message"] == "visible in the dump" for r in section["recent"])
    finally:
        root.handlers[:] = before


def test_install_keeps_warnings_on_stderr_when_root_had_no_handler(capsys):
    root = logging.getLogger()
    before = list(root.handlers)
    root.handlers[:] = []
    try:
        logs.install_log_capture()
        logging.getLogger("vmn_exp.diag_stderr").warning("still printed")
    finally:
        root.handlers[:] = before
    assert "still printed" in capsys.readouterr().err
