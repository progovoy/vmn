"""FinalRetry: a run's last upload is retried until it lands or is abandoned.

Pure unit tests: the attempt and the wait are fakes, nothing sleeps.
"""
from vmn_exp.core.final_retry import FinalRetry


class FlakyAttempt:
    """Raises for its first *failures* calls, then records the item."""

    def __init__(self, failures):
        self.failures = failures
        self.landed = []

    def __call__(self, item):
        if self.failures:
            self.failures -= 1
            raise OSError("remote down")
        self.landed.append(item)


class FakeWait:
    """Records each delay; reports 'abandoned' after *abandon_after* waits."""

    def __init__(self, abandon_after=None):
        self.delays = []
        self._abandon_after = abandon_after

    def __call__(self, delay):
        self.delays.append(delay)
        return self._abandon_after is not None and len(self.delays) >= self._abandon_after


def test_an_attempt_that_fails_once_is_retried_and_lands():
    attempt, wait = FlakyAttempt(failures=1), FakeWait()
    retry = FinalRetry(attempt, wait)

    retry.run("final")

    assert attempt.landed == ["final"]
    assert retry.landed is True
    assert wait.delays == [0.5]


def test_abandoning_stops_the_retries_and_keeps_the_error():
    attempt, wait = FlakyAttempt(failures=100), FakeWait(abandon_after=2)
    retry = FinalRetry(attempt, wait)

    retry.run("final")

    assert attempt.landed == []
    assert retry.landed is False
    assert isinstance(retry.error, OSError)
    assert len(wait.delays) == 2


def test_delays_double_up_to_the_cap():
    attempt, wait = FlakyAttempt(failures=6), FakeWait()
    retry = FinalRetry(attempt, wait)

    retry.run("final")

    assert wait.delays == [0.5, 1, 2, 5, 5, 5]
    assert retry.landed is True
