"""In-memory fakes for a run's final uploads (state publisher, log sync)."""
import threading

from vmn_exp.storage.base import NO_FILE

WAIT_SEC = 10  # a bound on blocking waits in the tests, never slept


class FakeAbandon:
    """The abandon signal a final retry waits on, without any real delay.

    Each ``wait(delay)`` is recorded and returns at once, unless *blocking*:
    then it waits until :meth:`proceed` (retry) or :meth:`set` (abandon)."""

    def __init__(self, blocking=False):
        self.delays = []
        self.waiting = threading.Event()
        self._go = threading.Event()
        self._abandoned = False
        if not blocking:
            self._go.set()

    def wait(self, delay):
        self.delays.append(delay)
        self.waiting.set()
        self._go.wait(WAIT_SEC)
        return self._abandoned

    def proceed(self):
        self._go.set()

    def set(self):
        self._abandoned = True
        self._go.set()


class FailingJob:
    """A sync job that raises for its first *failures* calls."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise OSError("remote down")


class FakeRemoteState:
    """A remote-only store of one run's state with version tokens, whose
    conditional saves raise for the first *failures* calls."""

    def __init__(self, failures=0, stored=None):
        self.failures = failures
        self.data = stored
        self.token = "t0" if stored is not None else None
        self.attempts = 0
        self.attempted = threading.Event()

    def is_remote(self):
        return True

    def load_file(self, app_name, verstr, filename):
        return self.data

    def load_file_with_token(self, app_name, verstr, filename):
        return self.data, self.token

    def save_file_if_match(self, app_name, verstr, filename, data, etag):
        self.attempts += 1
        self.attempted.set()
        if self.failures:
            self.failures -= 1
            raise OSError("remote down")
        current = NO_FILE if self.token is None else self.token
        if etag != current and etag is not None:
            return False, self.token
        self.data, self.token = data, f"t{self.attempts}"
        return True, self.token
