"""At every store size the ui recommends free-threaded Python. A 737k-run
ui reached 112 GB RSS after a cold index on 3.14 (GIL) against 74 GB on
3.14t, and 3.15.2t held 18 GB after 40 minutes (plan 31 D2). So a huge
store on a GIL build gets the same 3.15t hint as a large one, and a
free-threaded ui is never told to go back to the GIL."""
import logging

from vmn_exp.ui import gil_hint
from vmn_exp.ui.gil_hint import LARGE_STORE_RECORDS, GilHint

LOGGER = "vmn"
HUGE = 737_000


def _hints(caplog):
    return [r for r in caplog.records if r.name == LOGGER]


def test_a_huge_store_with_the_gil_on_is_told_to_go_free_threaded(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: True).note(HUGE)
    [hint] = _hints(caplog)
    assert hint.levelno == logging.WARNING
    assert "uvx --python 3.15t" in hint.getMessage()
    assert "Large stores" in hint.getMessage()


def test_a_huge_store_on_free_threaded_python_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: False).note(HUGE)
    assert _hints(caplog) == []


def test_there_is_no_gil_build_warning_left():
    assert not hasattr(gil_hint, "HUGE_HINT")
    assert not hasattr(gil_hint, "FREE_THREADED_MAX_RECORDS")
    assert HUGE > LARGE_STORE_RECORDS
