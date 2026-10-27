"""Past a few hundred thousand runs free-threaded Python stops paying off:
its allocator (mimalloc, per-thread heaps) keeps what each long-lived
worker thread once allocated, and every automatic collection stops the
whole process to scan the whole heap. A 486k-run server grew from 28 to
250 GiB with two-minute stalls on 3.14t. So the ui recommends 3.14t only
below :data:`FREE_THREADED_MAX_RECORDS` runs, and above it a free-threaded
ui says once to run on a GIL build instead."""
import logging

from vmn_exp.ui.gil_hint import FREE_THREADED_MAX_RECORDS, LARGE_STORE_RECORDS, GilHint

LOGGER = "vmn"


def _hints(caplog):
    return [r for r in caplog.records if r.name == LOGGER]


def test_the_bound_is_above_the_free_threaded_hint():
    assert FREE_THREADED_MAX_RECORDS > LARGE_STORE_RECORDS


def test_a_huge_store_with_the_gil_on_is_not_told_to_go_free_threaded(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: True).note(FREE_THREADED_MAX_RECORDS)
    assert _hints(caplog) == []


def test_a_huge_store_on_free_threaded_python_is_told_to_use_the_gil_build(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: False).note(FREE_THREADED_MAX_RECORDS)
    [hint] = _hints(caplog)
    assert hint.levelno == logging.WARNING
    message = hint.getMessage()
    assert "GIL" in message and "garbage collection" in message
    assert "Large stores" in message


def test_the_huge_store_warning_is_logged_once(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    hint = GilHint(gil_enabled=lambda: False)
    for _ in range(3):
        hint.note(FREE_THREADED_MAX_RECORDS * 2)
    assert len(_hints(caplog)) == 1


def test_a_store_below_the_bound_on_free_threaded_python_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    GilHint(gil_enabled=lambda: False).note(FREE_THREADED_MAX_RECORDS - 1)
    assert _hints(caplog) == []
