"""A background step's failure streak is logged without flooding: a WARNING
with the traceback at its start, again at most every ``LOG_EVERY_SEC`` with
the failure count and last error, and once when it recovers."""
import logging

import pytest

from vmn_exp.ui.failure_streak import LOG_EVERY_SEC, FailureStreak

LOGGER = logging.getLogger("test.failure_streak")


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def streak(clock):
    return FailureStreak("Index refresh of app", LOGGER, clock=clock)


def _fail(streak, message="storage went away"):
    try:
        raise RuntimeError(message)
    except RuntimeError as exc:
        streak.failed(exc)


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_streak_logs_a_warning_with_the_traceback_at_its_start(streak, caplog):
    caplog.set_level(logging.DEBUG)
    _fail(streak)
    (record,) = _warnings(caplog)
    assert "Index refresh of app" in record.getMessage()
    assert record.exc_info is not None
    assert streak.failing and streak.failures == 1
    assert streak.last_error == "RuntimeError('storage went away')"


def test_a_streak_stays_quiet_until_the_log_interval_passes(streak, clock, caplog):
    caplog.set_level(logging.DEBUG)
    _fail(streak)
    for _ in range(5):
        clock.now += 10
        _fail(streak)
    assert len(_warnings(caplog)) == 1


def test_a_long_streak_warns_again_with_its_count_and_last_error(streak, clock, caplog):
    caplog.set_level(logging.DEBUG)
    _fail(streak)
    clock.now += LOG_EVERY_SEC / 2
    _fail(streak)
    clock.now += LOG_EVERY_SEC / 2
    _fail(streak, "bucket gone")
    warnings = _warnings(caplog)
    assert len(warnings) == 2
    message = warnings[1].getMessage()
    assert "3 failures" in message and "bucket gone" in message
    assert warnings[1].exc_info is not None
    clock.now += 1
    _fail(streak)
    assert len(_warnings(caplog)) == 2  # the next one is LOG_EVERY_SEC later


def test_a_recovery_is_logged_once(streak, clock, caplog):
    _fail(streak)
    _fail(streak)
    clock.now += 120
    streak.succeeded()
    streak.succeeded()
    warnings = _warnings(caplog)
    assert len(warnings) == 2
    assert "recovered" in warnings[1].getMessage() and "2 failures" in warnings[1].getMessage()
    assert not streak.failing and streak.failures == 0 and streak.last_error is None


def test_a_success_without_failures_logs_nothing(streak, caplog):
    caplog.set_level(logging.DEBUG)
    streak.succeeded()
    assert caplog.records == []
